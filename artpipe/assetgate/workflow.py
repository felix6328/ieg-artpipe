"""Transactions for version selection, jobs and human review."""
from .database import clock, encode, identifier, record
from .library import MissingRecord
from .storage import BadAsset

OPERATIONS = ("apply_transforms", "recalculate_normals", "smart_uv")
FORMATS = {"GLB", "GLTF", "FBX", "OBJ"}
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELED"}


class Conflict(ValueError):
    """The requested operation conflicts with the current workspace state."""


def stages(operation, parameters):
    if operation == "inspect":
        return ["inspect"]
    if operation == "process":
        return ["inspect_source", *parameters["operations"], "convert", "recheck"]
    return ["package"]


def nodes_for(operation, parameters):
    return [{"name": name, "status": "PENDING"} for name in stages(operation, parameters)]


def get_run(db, run_id):
    row = record(db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone())
    if row is None:
        raise MissingRecord("找不到任务")
    return row


def get_version(db, version_id):
    row = record(db.execute("SELECT * FROM versions WHERE version_id = ?", (version_id,)).fetchone())
    if row is None:
        raise MissingRecord("找不到模型版本")
    return row


def latest(db, table, version_id):
    # Table is selected internally, never from request input.
    return record(db.execute(f"""SELECT * FROM {table} WHERE asset_version_id = ?
                                 ORDER BY created_at DESC, rowid DESC LIMIT 1""", (version_id,)).fetchone())


def approval(db, version):
    if version["freshness"] == "STALE":
        raise Conflict("此版本已过时，请从有效版本重新处理")
    report = latest(db, "reports", version["version_id"])
    review = latest(db, "reviews", version["version_id"])
    if not (report and review and review["report_id"] == report["report_id"] and review["decision"] == "APPROVED"):
        raise Conflict("请先对最新 QA 报告完成人工审核")
    if report["summary"]["counts"]["FAIL"] or not report["summary"]["metrics"]:
        raise Conflict("请先完成实际检查并解决阻断项")
    if report["summary"].get("adapter_mode") != "BLENDER":
        raise Conflict("导出需要真实 Blender 的检查报告")
    return report, review


def change_head(db, asset_id, version_id):
    asset = db.execute("SELECT current_version_id FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
    previous = asset["current_version_id"]
    if previous == version_id:
        return
    all_versions = {row["version_id"]: row["parent_version_id"] for row in db.execute(
        "SELECT version_id,parent_version_id FROM versions WHERE asset_id = ?", (asset_id,))}

    def ancestry(head):
        chain = set()
        while head:
            chain.add(head)
            head = all_versions[head]
        return chain

    stale = ancestry(previous) - ancestry(version_id)
    # Mark all work below an abandoned upstream branch.
    for version, parent in all_versions.items():
        if ancestry(parent) & stale:
            stale.add(version)
    for version in stale:
        db.execute("UPDATE versions SET freshness = 'STALE' WHERE version_id = ?", (version,))
        db.execute("""UPDATE runs SET freshness = 'STALE'
                      WHERE asset_version_id = ? OR output_version_id = ?""", (version, version))
    db.execute("UPDATE assets SET current_version_id = ?, head_epoch = head_epoch + 1 WHERE asset_id = ?",
               (version_id, asset_id))


class Workflow:
    """Queue local work and store review decisions for an exact report."""

    def __init__(self, library):
        self.library = library
        self.db = library.db

    def _queue(self, db, version, operation, parameters, retry_of=None):
        if version["freshness"] == "STALE":
            raise Conflict("源版本已过时")
        if operation == "export":
            report, review = approval(db, version)
            parameters = {"report_id": report["report_id"], "review_id": review["review_id"]}
        packed = encode(parameters)
        duplicate = db.execute("""SELECT * FROM runs WHERE asset_version_id = ? AND operation_type = ?
                                  AND parameters = ? AND status IN ('PENDING','RUNNING') AND freshness != 'STALE'""",
                               (version["version_id"], operation, packed)).fetchone()
        if duplicate:
            return record(duplicate)
        epoch = db.execute("SELECT head_epoch FROM assets WHERE asset_id = ?", (version["asset_id"],)).fetchone()[0]
        run_id = identifier()
        db.execute("""INSERT INTO runs(run_id,asset_version_id,operation_type,status,input_files,parameters,nodes,
                      created_at,retry_of,head_epoch) VALUES(?,?,?,'PENDING',?,?,?,?,?,?)""",
                   (run_id, version["version_id"], operation, encode(version["files"]), packed,
                    encode(nodes_for(operation, parameters)), clock(), retry_of, epoch))
        return get_run(db, run_id)

    def queue_inspection(self, db, version_id):
        return self._queue(db, get_version(db, version_id), "inspect", {})

    def submit(self, version_id, operation, parameters=None):
        parameters = parameters or {}
        if operation == "process":
            operations = parameters["operations"]
            if set(operations) - set(OPERATIONS) or len(operations) != len(set(operations)):
                raise BadAsset("处理操作无效或重复")
            if parameters["target_format"] is not None and parameters["target_format"] not in FORMATS:
                raise BadAsset("目标格式无效")
            if not (operations or parameters["target_format"]):
                raise BadAsset("请选择至少一种处理操作或目标格式")
            parameters = {**parameters, "operations": [op for op in OPERATIONS if op in operations]}
        elif operation not in {"inspect", "export"}:
            raise BadAsset("任务类型无效")
        with self.db.connect(write=True) as db:
            return self._queue(db, get_version(db, version_id), operation, parameters)

    def run(self, run_id):
        with self.db.connect() as db:
            return get_run(db, run_id)

    def cancel(self, run_id):
        with self.db.connect(write=True) as db:
            row = get_run(db, run_id)
            if row["status"] == "PENDING":
                for node in row["nodes"]:
                    node["status"] = "CANCELED"
                db.execute("""UPDATE runs SET cancel_requested = 1,status = 'CANCELED',completed_at = ?,nodes = ?
                              WHERE run_id = ?""", (clock(), encode(row["nodes"]), run_id))
            elif row["status"] == "RUNNING":
                db.execute("UPDATE runs SET cancel_requested = 1 WHERE run_id = ?", (run_id,))
            return get_run(db, run_id)

    def retry(self, run_id):
        with self.db.connect(write=True) as db:
            row = get_run(db, run_id)
            if row["status"] not in {"FAILED", "CANCELED"}:
                raise Conflict("请选择失败或取消的任务")
            version = get_version(db, row["asset_version_id"])
            return self._queue(db, version, row["operation_type"], row["parameters"], retry_of=run_id)

    def select(self, version_id):
        with self.db.connect(write=True) as db:
            version = get_version(db, version_id)
            if version["freshness"] == "STALE":
                raise Conflict("已过时的结果仍可对照查看，请从有效上游版本重新处理")
            change_head(db, version["asset_id"], version_id)
        return self.library.detail(version["asset_id"])

    def review(self, version_id, report_id, reviewer, decision, note):
        with self.db.connect(write=True) as db:
            version = get_version(db, version_id)
            report = latest(db, "reports", version_id)
            if version["freshness"] == "STALE" or not report or report["report_id"] != report_id:
                raise Conflict("版本或报告已经更新，请刷新后审核")
            if decision == "APPROVED":
                summary = report["summary"]
                if summary["counts"]["FAIL"] or not summary["metrics"] or summary["adapter_mode"] != "BLENDER":
                    raise Conflict("通过审核需要真实 Blender 检查，且没有阻断项")
            review_id = identifier()
            db.execute("""INSERT INTO reviews(review_id,asset_version_id,report_id,reviewer,decision,note,created_at)
                          VALUES(?,?,?,?,?,?,?)""", (review_id, version_id, report_id, reviewer, decision, note, clock()))
            return latest(db, "reviews", version_id)

    def export_file(self, run_id):
        with self.db.connect() as db:
            run = get_run(db, run_id)
            if run["status"] != "SUCCEEDED" or not run["export_file"]:
                raise MissingRecord("没有可下载的资产包")
            verify_export(db, run, get_version(db, run["asset_version_id"]))
            return self.library.path(run["export_file"])


def verify_export(db, run, version):
    report, review = approval(db, version)
    if (run["parameters"]["report_id"], run["parameters"]["review_id"]) != (report["report_id"], review["review_id"]):
        raise Conflict("报告或审核已经更新，请重新导出")
    return report, review
