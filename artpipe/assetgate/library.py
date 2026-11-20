"""Upload and query the local asset library."""
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil

from .database import Database, clock, encode, identifier, record
from .storage import BadAsset, MODELS, confined, copy_limited, digest, parts, unpack, validate_model


class MissingRecord(LookupError):
    """Asset, version or run does not exist."""


class Library:
    """Local storage paths and the SQLite asset catalog."""

    def __init__(self, root, config):
        self.root = root.resolve()
        self.config = config
        self.db = Database(self.root)
        for folder in ("assets", "jobs", "staging"):
            self.path(folder).mkdir(exist_ok=True)

    def path(self, name):
        return confined(self.root, name)

    def asset_list(self):
        with self.db.connect() as db:
            rows = db.execute("""SELECT a.*, v.version_number, v.file_format, v.preview_file,
                                        (SELECT count(*) FROM versions WHERE asset_id = a.asset_id) versions,
                                        (SELECT count(*) FROM runs r JOIN versions rv ON r.asset_version_id = rv.version_id
                                          WHERE rv.asset_id = a.asset_id AND r.status IN ('PENDING','RUNNING')) active_runs,
                                        EXISTS(SELECT 1 FROM reviews w WHERE w.review_id = (
                                          SELECT review_id FROM reviews WHERE asset_version_id = v.version_id
                                          ORDER BY created_at DESC, rowid DESC LIMIT 1
                                        ) AND w.report_id = (SELECT report_id FROM reports
                                          WHERE asset_version_id = v.version_id
                                          ORDER BY created_at DESC, rowid DESC LIMIT 1) AND w.decision = 'APPROVED') approved
                                 FROM assets a JOIN versions v ON v.version_id = a.current_version_id
                                 ORDER BY a.created_at DESC""")
            return [record(row) for row in rows]

    def version(self, version_id):
        with self.db.connect() as db:
            row = db.execute("SELECT * FROM versions WHERE version_id = ?", (version_id,)).fetchone()
        if row is None:
            raise MissingRecord("找不到模型版本")
        return record(row)

    def detail(self, asset_id):
        with self.db.connect() as db:
            db.execute("BEGIN")
            asset = record(db.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone())
            if asset is None:
                raise MissingRecord("找不到资产")
            queries = {
                "versions": "SELECT * FROM versions WHERE asset_id = ? ORDER BY version_number DESC",
                "reports": """SELECT r.* FROM reports r JOIN versions v ON v.version_id = r.asset_version_id
                              WHERE v.asset_id = ? ORDER BY r.created_at DESC""",
                "runs": """SELECT r.* FROM runs r JOIN versions v ON v.version_id = r.asset_version_id
                           WHERE v.asset_id = ? ORDER BY r.created_at DESC""",
                "baselines": """SELECT b.*, b.run_id report_id, r.output_version_id FROM processing_baselines b
                                 JOIN runs r ON b.run_id = r.run_id JOIN versions v ON v.version_id = b.asset_version_id
                                 WHERE v.asset_id = ? ORDER BY b.created_at DESC""",
                "reviews": """SELECT r.* FROM reviews r JOIN versions v ON v.version_id = r.asset_version_id
                              WHERE v.asset_id = ? ORDER BY r.created_at DESC""",
            }
            for key, query in queries.items():
                asset[key] = [record(row) for row in db.execute(query, (asset_id,))]
            return asset

    def upload(self, stream, filename, name, asset_type, model_entry=None, *, after_create=None):
        filename = filename or "upload"
        if len(parts(filename).parts) != 1:
            raise BadAsset("上传文件名不能包含目录")
        suffix = Path(filename).suffix.lower()
        if suffix not in MODELS | {".zip"}:
            raise BadAsset("请选择 GLB、glTF、FBX、OBJ 或 ZIP")
        asset_id, version_id = identifier(), identifier()
        version_folder = f"assets/{asset_id}/{version_id}"
        final = self.path(version_folder)
        limits = self.config["upload"]
        with TemporaryDirectory(dir=self.path("staging")) as temp:
            stage = Path(temp)
            models = stage / "model"
            models.mkdir()
            if suffix == ".zip":
                upload_dir = stage / "original"
                upload_dir.mkdir()
                original = upload_dir / filename
                copy_limited(stream, original, limits["max_bytes"])
                unpack(original, models, limits)
            else:
                original = models / filename
                copy_limited(stream, original, limits["max_bytes"])
            candidates = sorted(p for p in models.rglob("*") if p.is_file() and p.suffix.lower() in MODELS)
            if model_entry:
                model = confined(models, parts(model_entry).as_posix())
                if model not in candidates:
                    raise BadAsset("指定的主模型不在 ZIP 中")
            elif len(candidates) == 1:
                model = candidates[0]
            else:
                raise BadAsset("ZIP 需要一个主模型，多个模型时请填写 ZIP 内主模型路径")
            validate_model(model, models)
            relative = model.relative_to(stage).as_posix()
            files = [f"{version_folder}/{p.relative_to(stage).as_posix()}" for p in sorted(models.rglob("*")) if p.is_file()]
            stamp = clock()
            final.parent.mkdir()
            try:
                stage.rename(final)
                with self.db.connect(write=True) as db:
                    db.execute("INSERT INTO assets(asset_id,name,asset_type,created_at) VALUES(?,?,?,?)",
                               (asset_id, name.strip() or model.stem, asset_type.strip() or "model", stamp))
                    db.execute("""INSERT INTO versions(version_id,asset_id,version_number,source_file,
                                  file_hash,file_format,created_at,files,upload_hash)
                                  VALUES(?,?,1,?,?,?,?,?,?)""",
                               (version_id, asset_id, f"{version_folder}/{relative}", digest(final / relative),
                                model.suffix[1:].upper(), stamp, encode(files), digest(final / original.relative_to(stage))))
                    db.execute("UPDATE assets SET current_version_id = ? WHERE asset_id = ?", (version_id, asset_id))
                    if after_create:
                        after_create(db, version_id)
            except Exception:
                shutil.rmtree(final.parent)
                raise
        return self.detail(asset_id)
