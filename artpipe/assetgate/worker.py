"""Restartable serial worker for Blender and package jobs."""
from __future__ import annotations

from contextlib import contextmanager
from threading import Event, Thread
from zipfile import ZIP_DEFLATED, ZipFile
import fcntl
import logging
import shutil

from .blender import BlenderError, Job, JobCanceled
from .database import clock, encode, identifier, record
from .qa import run_qa
from .storage import MODELS, BadAsset, digest, validate_model
from .workflow import Conflict, change_head, get_run, get_version, nodes_for, verify_export

logger = logging.getLogger(__name__)


class Task:
    """Manage one claimed job, its nodes and its local files."""

    def __init__(self, worker, run):
        self.worker = worker
        self.run = run
        self.run_id = run["run_id"]
        self.db = worker.library.db
        self.library = worker.library
        self.version = self.library.version(run["asset_version_id"])
        self.job = Job(self.library.path(f"jobs/{self.run_id}"))
        self.adapter = worker.adapter
        self.nodes = run["nodes"]

    def canceled(self):
        if self.worker.stop.is_set():
            return True
        with self.db.connect() as db:
            return bool(db.execute("SELECT cancel_requested FROM runs WHERE run_id = ?", (self.run_id,)).fetchone()[0])

    def check_cancel(self):
        if self.canceled():
            raise JobCanceled()

    def persist_nodes(self):
        with self.db.connect(write=True) as db:
            db.execute("UPDATE runs SET nodes = ? WHERE run_id = ?", (encode(self.nodes), self.run_id))

    @contextmanager
    def node(self, name):
        self.check_cancel()
        node = next(item for item in self.nodes if item["name"] == name)
        node.update(status="RUNNING", started_at=clock())
        self.persist_nodes()
        try:
            yield
            self.check_cancel()
        except JobCanceled:
            node.update(status="CANCELED", completed_at=clock())
            raise
        except Exception as exc:
            node.update(status="FAILED", completed_at=clock(), error_message=str(exc))
            raise
        else:
            node.update(status="SUCCEEDED", completed_at=clock())
        finally:
            self.persist_nodes()

    def inputs(self):
        stored = self.library.path(self.version["source_file"])
        package = self.library.path(f"assets/{self.version['asset_id']}/{self.version['version_id']}/model")
        for name in self.version["files"]:
            source = self.library.path(name)
            target = self.job.input / source.relative_to(package)
            target.parent.mkdir(parents=True, exist_ok=True)
            self.check_cancel()
            if source.is_file():
                shutil.copyfile(source, target)
        model = self.job.input / stored.relative_to(package)
        if model.is_file() and digest(model) != self.version["file_hash"]:
            raise BadAsset("源文件 SHA256 已变化")
        return model

    def inspect(self, source, package, stage, preview=None, *, failed_report_for=None):
        try:
            validate_model(source, package)
            result = self.adapter.inspect_model(self.job, source, self.canceled, stage=stage, preview=preview,
                                                area_epsilon=self.library.config["rules"]["degenerate_area_epsilon"])
        except (BlenderError, BadAsset, OSError) as exc:
            if failed_report_for:
                with self.db.connect(write=True) as db:
                    if get_run(db, self.run_id)["cancel_requested"]:
                        raise JobCanceled() from exc
                    report = run_qa(source, package, self.library.config, error=str(exc),
                                    parse_failed=getattr(exc, "parse_failed", False))
                    self.save_report(db, failed_report_for, report)
            raise
        return run_qa(source, package, self.library.config, inspection=result), bool(result.get("preview_ready"))

    def save_report(self, db, version_id, report):
        report["summary"]["adapter_mode"] = self.adapter.mode
        db.execute("""INSERT INTO reports(report_id,asset_version_id,run_id,ruleset_version,summary,findings,created_at)
                      VALUES(?,?,?,?,?,?,?)""",
                   (identifier(), version_id, self.run_id, report["ruleset_version"], encode(report["summary"]),
                    encode(report["findings"]), clock()))

    def complete(self, db, *, outputs=(), output_version=None, export=None, freshness=None):
        run = get_run(db, self.run_id)
        if self.worker.stop.is_set() or run["cancel_requested"]:
            raise JobCanceled()
        db.execute("""UPDATE runs SET status = 'SUCCEEDED', completed_at = ?, output_files = ?, output_version_id = ?,
                     export_file = ?, freshness = ? WHERE run_id = ?""",
                   (clock(), encode(list(outputs)), output_version, export, freshness or run["freshness"], self.run_id))

    def inspect_input(self, model):
        preview = "preview.glb"
        with self.node("inspect"):
            report, ready = self.inspect(model, self.job.input, "inspect", preview,
                                         failed_report_for=self.version["version_id"])
        outfile = self.relative(self.job.output / preview) if ready else None
        with self.db.connect(write=True) as db:
            self.save_report(db, self.version["version_id"], report)
            if outfile:
                db.execute("UPDATE versions SET preview_file = ? WHERE version_id = ?",
                           (outfile, self.version["version_id"]))
            self.complete(db, outputs=[outfile] if outfile else [])

    def process_input(self, source):
        params = self.run["parameters"]
        with self.node("inspect_source"):
            source_report, _ = self.inspect(source, self.job.input, "inspect_source",
                                            failed_report_for=self.version["version_id"])
            blocked = {"FILE_REFERENCES", "IMAGE_PATH", "IMAGE_EXISTS", "MESH_OBJECTS", "TRIANGLES", "INVALID_VERTICES"}
            bad = [finding for finding in source_report["findings"] if finding["status"] == "FAIL"
                   and finding["rule_id"] in blocked]
            # Budget findings are allowed when the source contains usable triangles.
            actual = source_report["summary"]["metrics"]["triangles"]
            bad = [f for f in bad if f["rule_id"] != "TRIANGLES" or not actual]
            if bad:
                with self.db.connect(write=True) as db:
                    self.save_report(db, self.version["version_id"], source_report)
                raise BadAsset("源模型需先修复：" + "、".join(f["rule_name"] for f in bad))
            # Save baseline for comparison when the user processed without an initial QA.
            with self.db.connect(write=True) as db:
                if db.execute("SELECT 1 FROM reports WHERE asset_version_id = ?",
                              (self.version["version_id"],)).fetchone() is None:
                    self.save_report(db, self.version["version_id"], source_report)
        for operation in params["operations"]:
            target = f"intermediate/{operation}.blend"
            with self.node(operation):
                self.adapter.process_model(self.job, source, target, operation, params, self.canceled)
            source = self.job.output / target
        suffix = (params["target_format"] or self.version["file_format"]).lower()
        target = f"final/model.{suffix}"
        with self.node("convert"):
            self.adapter.export_model(self.job, source, target, self.canceled)
        output = self.job.output / target
        with self.node("recheck"):
            report, ready = self.inspect(output, output.parent, "recheck", "preview.glb")
        self.publish(output, report, ready, source_report)

    def publish(self, output, report, ready, baseline):
        version_id = self.run_id
        asset_id = self.version["asset_id"]
        folder = self.library.path(f"assets/{asset_id}/{version_id}")
        model_dir = folder / "model"
        published = False
        try:
            with self.db.connect(write=True) as db:
                run = get_run(db, self.run_id)
                epoch = db.execute("SELECT head_epoch FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()[0]
                parent = get_version(db, self.version["version_id"])
                stale = run["freshness"] == "STALE" or parent["freshness"] == "STALE" or epoch != run["head_epoch"]
                freshness = "STALE" if stale else "CURRENT"
                number = db.execute("SELECT max(version_number) + 1 FROM versions WHERE asset_id = ?", (asset_id,)).fetchone()[0]
                # A replay after an interruption can replace only its own unpublished directory.
                if folder.exists() and db.execute("SELECT 1 FROM versions WHERE version_id = ?", (version_id,)).fetchone() is None:
                    shutil.rmtree(folder)
                shutil.copytree(output.parent, model_dir)
                files = [self.relative(p) for p in sorted(model_dir.rglob("*")) if p.is_file()]
                model = model_dir / output.name
                preview = self.relative(self.job.output / "preview.glb") if ready else None
                db.execute("""INSERT INTO versions(version_id,asset_id,version_number,parent_version_id,source_file,
                              file_hash,file_format,created_at,files,preview_file,freshness)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                           (version_id, asset_id, number, parent["version_id"], self.relative(model), digest(model),
                            model.suffix[1:].upper(), clock(), encode(files), preview, freshness))
                self.save_report(db, version_id, report)
                baseline["summary"]["adapter_mode"] = self.adapter.mode
                db.execute("""INSERT INTO processing_baselines(run_id, asset_version_id, ruleset_version,
                              summary, findings, created_at) VALUES(?,?,?,?,?,?)""",
                           (self.run_id, parent["version_id"], baseline["ruleset_version"], encode(baseline["summary"]),
                            encode(baseline["findings"]), self.run["started_at"]))
                if not stale:
                    change_head(db, asset_id, version_id)
                self.complete(db, outputs=files + ([preview] if preview else []), output_version=version_id,
                              freshness=freshness)
            published = True
        finally:
            if not published and folder.exists():
                shutil.rmtree(folder)

    def package(self):
        target = self.job.output / "asset-package.zip"
        with self.node("package"):
            with self.db.connect() as db:
                version = get_version(db, self.version["version_id"])
                report, review = verify_export(db, self.run, version)
                lineage = [version]
                while lineage[-1]["parent_version_id"]:
                    lineage.append(get_version(db, lineage[-1]["parent_version_id"]))
                asset = record(db.execute("SELECT * FROM assets WHERE asset_id = ?", (version["asset_id"],)).fetchone())
                related = {row["version_id"] for row in lineage}
                history = [record(row) for row in db.execute(
                    """SELECT r.* FROM runs r JOIN versions v ON r.asset_version_id = v.version_id
                       WHERE v.asset_id = ? AND operation_type != 'export' ORDER BY r.created_at""", (asset["asset_id"],))
                           if row["asset_version_id"] in related
                           and (row["output_version_id"] is None or row["output_version_id"] in related)]
            directory = self.library.path(f"assets/{asset['asset_id']}/{version['version_id']}/model")
            files = []
            with ZipFile(target, "w", compression=ZIP_DEFLATED, compresslevel=3) as bundle:
                for name in version["files"]:
                    self.check_cancel()
                    path = self.library.path(name)
                    if name != version["source_file"] and path.suffix.lower() in MODELS:
                        continue
                    entry = f"model/{path.relative_to(directory).as_posix()}"
                    checksum = digest(path)
                    if name == version["source_file"] and checksum != version["file_hash"]:
                        raise BadAsset("版本模型的 SHA256 与登记值不符")
                    bundle.write(path, entry)
                    files.append({"path": entry, "sha256": checksum, "bytes": path.stat().st_size})
                model = self.library.path(version["source_file"]).relative_to(directory).as_posix()
                manifest = {"schema_version": 1, "asset_id": asset["asset_id"], "name": asset["name"],
                            "asset_type": asset["asset_type"], "version_id": version["version_id"],
                            "version_number": version["version_number"], "model": f"model/{model}",
                            "format": version["file_format"], "files": files, "qa_report_id": report["report_id"],
                            "review_id": review["review_id"], "engine_import_validation": "NOT_CHECKED"}
                for name, payload in (("manifest.json", manifest), ("qa_report.json", report),
                                      ("processing_history.json", history), ("version_info.json", lineage),
                                      ("review.json", review)):
                    bundle.writestr(name, encode(payload))
        with self.db.connect(write=True) as db:
            verify_export(db, self.run, get_version(db, self.version["version_id"]))
            entry = self.relative(target)
            self.complete(db, outputs=[entry], export=entry)

    def relative(self, path):
        return path.relative_to(self.library.root).as_posix()

    def execute(self):
        self.job.prepare()
        # Replaying an interrupted task must not reuse partially written artifacts.
        for folder in (self.job.input, self.job.output):
            shutil.rmtree(folder)
            folder.mkdir()
        self.check_cancel()
        if self.run["operation_type"] == "export":
            self.package()
        else:
            model = self.inputs()
            if self.run["operation_type"] == "inspect":
                self.inspect_input(model)
            else:
                self.process_input(model)

    def finish_error(self, exc):
        with self.db.connect(write=True) as db:
            row = get_run(db, self.run_id)
            if row["cancel_requested"]:
                status = "CANCELED"
            elif isinstance(exc, JobCanceled) and self.worker.stop.is_set():
                status = "PENDING"
            else:
                status = "FAILED"
            nodes = nodes_for(row["operation_type"], row["parameters"]) if status == "PENDING" else self.nodes
            if status == "CANCELED":
                for node in nodes:
                    if node["status"] in {"RUNNING", "PENDING"}:
                        node.update(status="CANCELED", completed_at=clock())
            db.execute("""UPDATE runs SET status = ?, nodes = ?, completed_at = ?, error_message = ?
                          WHERE run_id = ?""",
                       (status, encode(nodes), clock() if status != "PENDING" else None,
                        str(exc)[:6000] if status == "FAILED" else None, self.run_id))


class Worker:
    """Hold a storage-local process lock and claim jobs transactionally."""

    def __init__(self, library, adapter):
        self.library = library
        self.adapter = adapter
        self.stop = Event()

    @contextmanager
    def exclusive(self):
        with self.library.path("worker.lock").open("a+b") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            if hasattr(self.adapter, "worker_lock_fd"):
                self.adapter.worker_lock_fd = lock.fileno()
            try:
                yield True
            finally:
                if hasattr(self.adapter, "worker_lock_fd"):
                    self.adapter.worker_lock_fd = None

    def recover(self):
        with self.library.db.connect(write=True) as db:
            for row in db.execute("SELECT * FROM runs WHERE status = 'RUNNING'").fetchall():
                run = record(row)
                status = "CANCELED" if run["cancel_requested"] else "PENDING"
                nodes = nodes_for(run["operation_type"], run["parameters"])
                if status == "CANCELED":
                    for node in nodes:
                        node["status"] = status
                db.execute("""UPDATE runs SET status = ?, started_at = NULL, completed_at = ?, nodes = ?
                              WHERE run_id = ?""",
                           (status, clock() if status == "CANCELED" else None, encode(nodes), run["run_id"]))

    def claim(self):
        with self.library.db.connect(write=True) as db:
            row = db.execute("""SELECT * FROM runs WHERE status = 'PENDING'
                                ORDER BY created_at, run_id LIMIT 1""").fetchone()
            if not row:
                return None
            db.execute("""UPDATE runs SET status = 'RUNNING', started_at = ?, adapter_mode = ?
                          WHERE run_id = ?""", (clock(), self.adapter.mode, row["run_id"]))
            return get_run(db, row["run_id"])

    def run_one(self):
        run = self.claim()
        if run is None:
            return False
        task = Task(self, run)
        try:
            task.execute()
        except (BlenderError, BadAsset, JobCanceled, Conflict) as exc:
            task.finish_error(exc)
        except Exception as exc:
            logger.exception("AssetGate task %s failed", task.run_id)
            task.finish_error(exc)
        return True

    def serve(self):
        interval = self.library.config["worker"]["poll_seconds"]
        while not self.stop.is_set():
            with self.exclusive() as acquired:
                if acquired:
                    self.recover()
                    while not self.stop.is_set():
                        if not self.run_one():
                            self.stop.wait(interval)
                    return
            self.stop.wait(interval)

    @contextmanager
    def background(self):
        thread = Thread(target=self.serve, name="assetgate-worker", daemon=True)
        thread.start()
        try:
            yield
        finally:
            self.stop.set()
            thread.join()
