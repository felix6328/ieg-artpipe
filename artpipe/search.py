"""Structured filtering, Chinese glossary expansion, BM25 and OpenCLIP retrieval."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path, PurePosixPath
from functools import lru_cache
import json
import os
import re

import yaml

WORDS = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")
KINDS = {"han": "Han Chinese", "siege": "siege engine", "structure": "building or structural component"}


def tokens(text: str) -> list[str]:
    import jieba

    jieba.setLogLevel(30)
    words = []
    for part in WORDS.findall(text.casefold()):
        if part.isascii():
            words.append(part)
        else:
            words.extend(jieba.lcut(part))
    return list(dict.fromkeys(words))


def query_tokens(query: str, glossary: dict) -> tuple[list[str], str]:
    expansions = []
    remaining = query
    for term in sorted(glossary, key=len, reverse=True):
        if term in remaining:
            expansions.extend(glossary[term])
            remaining = remaining.replace(term, " ")
    return tokens(" ".join([query, *expansions])), " ".join(dict.fromkeys(expansions))


class Embedder:
    def __init__(self, options: dict, cache: Path):
        os.environ.setdefault("HF_HOME", str(cache.resolve()))
        import logging

        import open_clip
        import torch

        torch.set_num_threads(options["cpu_threads"])
        logging.getLogger("transformers").setLevel(logging.ERROR)
        model_name, checkpoint = options["model"], options["pretrained"]
        self.torch = torch
        checkpoint_file = cache / "manual/clip-xlmr.bin"
        model_weights = str(checkpoint_file) if checkpoint_file.is_file() else checkpoint
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=model_weights, device="cpu")
        self.model.eval()
        self.tokenize = open_clip.get_tokenizer(model_name)

    def encode_images(self, paths: list[Path]):
        from PIL import Image

        tensors = []
        for path in paths:
            with Image.open(path) as image:
                tensors.append(self.preprocess(image.convert("RGB")))
        with self.torch.inference_mode():
            features = self.model.encode_image(self.torch.stack(tensors))
            return self.torch.nn.functional.normalize(features, dim=-1).cpu().numpy()

    @lru_cache(maxsize=256)
    def encode_text(self, texts: tuple[str, ...]):
        with self.torch.inference_mode():
            features = self.model.encode_text(self.tokenize(list(texts)))
            features = self.torch.nn.functional.normalize(features, dim=-1).mean(dim=0)
            return self.torch.nn.functional.normalize(features, dim=-1).cpu().numpy()


class Search:
    def __init__(self, data: Path, config: Path, use_visual: bool = False):
        from rank_bm25 import BM25Okapi

        self.data = data
        self.options = yaml.safe_load(config.read_text(encoding="utf-8"))
        manifest = json.loads((data / "library/assets.json").read_text(encoding="utf-8"))
        self.assets = manifest["assets"]
        self.revision = manifest["revision"]
        if not self.assets:
            raise ValueError("检索目录为空，请先构建资产库")
        synonyms_by_alias = defaultdict(set)
        for chinese, aliases in self.options["glossary"].items():
            for alias in aliases:
                synonyms_by_alias[tuple(tokens(alias))].add(chinese)
        self.names = [tokens(PurePosixPath(a["path"]).stem) for a in self.assets]
        segments = []
        for item, names in zip(self.assets, self.names):
            alias_set = set(tokens(item["path"]))
            document = names * 2 + sorted(alias_set) + tokens(KINDS.get(item["category"], item["category"]))
            for english, chinese in synonyms_by_alias.items():
                if english and set(english) <= alias_set:
                    document.extend(word for label in sorted(chinese) for word in tokens(label))
            segments.append(document)
        self.lexical = BM25Okapi(segments)
        self.use_visual = use_visual
        self.encoder = None
        self.matrix = None

    def embed(self):
        import numpy as np

        target = self.data / "library/vectors.npz"
        references = [item["oid"] for item in self.assets]
        model_id = self.options["model"] + ":" + self.options["pretrained"]
        if target.is_file():
            with np.load(target, allow_pickle=False) as stored:
                if stored["oids"].tolist() == references and stored["model"].item() == model_id:
                    self.matrix = stored["matrix"]
                    return
        self._encoder()
        batch_size = self.options["batch_size"]
        path = self.data / "library/thumbs"
        matrix = [self.encoder.encode_images([path / item["thumbnail"] for item in self.assets[i:i+batch_size]])
                  for i in range(0, len(self.assets), batch_size)]
        self.matrix = np.concatenate(matrix, axis=0)
        temporary = target.with_suffix(".tmp.npz")
        np.savez_compressed(temporary, matrix=self.matrix, oids=references, model=model_id)
        temporary.replace(target)

    def _encoder(self):
        if self.encoder is None:
            self.encoder = Embedder(self.options, self.data / "huggingface")

    def rank(self, query: str, *, limit: int = 10, mode: str = "hybrid",
             category: str | None = None, max_faces: int | None = None, image: Path | None = None,
             visual_weight: float = 1.0) -> list[dict]:
        candidates = [i for i, asset in enumerate(self.assets)
                      if (category is None or asset["category"] == category)
                      and (max_faces is None or asset["triangles"] <= max_faces)]
        words, english = query_tokens(query, self.options["glossary"])
        if mode == "filename":
            exact = set(tokens(query))
            ranked = [(i, float(len(set(self.names[i]) & exact))) for i in candidates]
            return self._results(sorted((pair for pair in ranked if pair[1]), key=lambda pair: -pair[1]), limit)
        lexical = self.lexical.get_scores(words)
        ranks = [sorted((i for i in candidates if lexical[i] > 0), key=lambda i: (-lexical[i], i))]
        if self.use_visual and mode == "hybrid" and visual_weight > 0:
            if self.matrix is None:
                self.embed()
            self._encoder()
            if image:
                features = self.encoder.encode_images([image])[0]
            else:
                visual = [query] + ([f"A 3D game asset render of {english}"] if english else [])
                features = self.encoder.encode_text(tuple(visual))
            semantic = self.matrix @ features
            ranks.append(sorted(candidates, key=lambda i: (-semantic[i], i)))
        if len(ranks) == 1:
            return self._results([(i, float(lexical[i])) for i in ranks[0]], limit)
        fused = defaultdict(float)
        for rank, weight in zip(ranks, (1.0, visual_weight)):
            for index, candidate in enumerate(rank[:150], 1):
                fused[candidate] += weight / (self.options["rrf_k"] + index)
        return self._results(sorted(fused.items(), key=lambda pair: (-pair[1], pair[0])), limit)

    def _results(self, ranked, limit):
        return [dict(self.assets[i], score=round(value, 5)) for i, value in ranked[:limit]]
