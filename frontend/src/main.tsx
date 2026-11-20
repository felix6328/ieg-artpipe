import { type FormEvent, type ReactNode, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';

import { api, date, format, isActive, label, number, request, type AssetDetail, type AssetRow,
  type Engine, type Report, type Review, type Run, type Version } from './model';
import { Preview } from './preview';
import './workbench.css';

type Route = { page: 'dashboard' | 'assets' | 'jobs' | 'detail'; id?: string };
const route = (): Route => {
  const hash = window.location.hash.slice(1);
  if (hash.startsWith('asset/')) return { page: 'detail', id: hash.slice(6) };
  if (hash === 'assets' || hash === 'jobs') return { page: hash };
  return { page: 'dashboard' };
};

function Status({ value }: { value: string }) {
  return <span className={`ag-badge ag-${value.toLowerCase()}`}><i aria-hidden="true" />{label[value] || value}</span>;
}

function Empty({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="ag-empty">
    <div className="ag-empty-icon" aria-hidden="true">◇</div><h3>{title}</h3><p>{children}</p>{action}
  </div>;
}

function AssetTable({ rows, upload, dashboard }: { rows: AssetRow[]; upload: () => void; dashboard: boolean }) {
  const [query, setQuery] = useState('');
  const visible = rows.filter(row => `${row.name} ${row.asset_type} ${row.file_format}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="ag-panel">
    <header className="ag-panel-heading">
      <div><h2>{dashboard ? '最近资产' : '全部资产'}</h2><p>{number(rows.length)} 个本地资产</p></div>
      {dashboard ? <a href="#assets" className="ag-button">查看资产库 ↗</a> :
        <input className="ag-search" aria-label="筛选资产" type="search" placeholder="搜索名称、类型或格式" value={query}
          onChange={event => setQuery(event.target.value)} />}
    </header>
    {visible.length ? <div className="ag-scroll"><table className="ag-table">
      <thead><tr><th>资产</th><th>格式</th><th>版本</th><th>状态</th><th>上传时间</th><th></th></tr></thead>
      <tbody>{(dashboard ? visible.slice(0, 7) : visible).map(row => <tr key={row.asset_id}>
        <td><a className="ag-file" href={`#asset/${row.asset_id}`}><span className="ag-file-mark" aria-hidden="true">◇</span>
          <span><strong>{row.name}</strong><small>{row.asset_type}</small></span></a></td>
        <td><span className="ag-format">{row.file_format}</span></td>
        <td className="ag-mono">V{row.version_number}</td>
        <td><Status value={row.active_runs ? 'RUNNING' : row.approved ? 'APPROVED' : row.preview_file ? '待审核' : '待检查'} /></td>
        <td>{date(row.created_at)}</td><td><a href={`#asset/${row.asset_id}`} aria-label={`打开 ${row.name}`}>↗</a></td>
      </tr>)}</tbody>
    </table></div> : <Empty title={query ? '没有匹配资产' : '导入第一个模型'}
      action={query ? undefined : <button className="ag-primary" onClick={upload}>＋ 上传模型</button>}>
      {query ? '试试另一个名称、类型或格式。' : '支持 GLB、glTF、FBX、OBJ，以及包含外部贴图和模型依赖的 ZIP。'}
    </Empty>}
  </section>;
}

function Dashboard({ rows, engine, upload }: { rows: AssetRow[]; engine: Engine | null; upload: () => void }) {
  return <>
    <div className="ag-metrics">
      {[
        ['资产数量', rows.length, '已保存在本地资产库'],
        ['版本总数', rows.reduce((total, item) => total + item.versions, 0), '原始与处理后的版本'],
        ['执行队列', rows.reduce((total, item) => total + item.active_runs, 0), '排队或执行中的任务'],
        ['审核通过', rows.reduce((total, item) => total + item.approved, 0), '当前版本可导出'],
      ].map(([name, value, helper]) => <article className="ag-stat" key={name}>
        <span>{name}</span><strong>{value}</strong><small>{helper}</small>
      </article>)}
    </div>
    <AssetTable rows={rows} dashboard upload={upload} />
    {engine && <p className="ag-footnote">规则集 {engine.ruleset_version} · Blender {engine.blender_detected ? '已检测到可执行文件' : '未检测到可执行文件'}</p>}
  </>;
}

function UploadDialog({ close, uploaded, engine }: { close: () => void; uploaded: (asset: AssetDetail) => void; engine: Engine | null }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    if (!file) { setError('请选择一个模型或 ZIP。'); return; }
    if (engine && file.size > engine.max_upload_bytes) { setError('所选文件超出上传大小限制。'); return; }
    const form = new FormData(event.currentTarget);
    form.set('file', file);
    setBusy(true);
    try { uploaded(await request<AssetDetail>('/assets', 'POST', form)); }
    catch (problem) { setError(String(problem instanceof Error ? problem.message : problem)); }
    finally { setBusy(false); }
  }
  const zip = file?.name.toLowerCase().endsWith('.zip');
  return <dialog className="ag-dialog" ref={dialog} onCancel={event => { event.preventDefault(); if (!busy) close(); }}>
    <form onSubmit={event => void submit(event)}>
      <header className="ag-panel-heading"><div><h2>上传模型</h2><p>上传后自动安排 Blender 质量检查。</p></div>
        <button type="button" disabled={busy} onClick={close} aria-label="关闭">×</button></header>
      <div className="ag-dialog-body">
        <input ref={input} type="file" name="file" accept=".glb,.gltf,.fbx,.obj,.zip" onChange={event =>
          setFile(event.target.files?.[0] ?? null)} className="ag-visually-hidden" tabIndex={-1} />
        <button type="button" className="ag-drop" disabled={busy} onClick={() => input.current?.click()}
          onDragOver={event => event.preventDefault()} onDrop={event => {
            event.preventDefault();
            if (!busy) setFile(event.dataTransfer.files[0] ?? null);
          }}><span aria-hidden="true">↑</span><strong>{file ? file.name : '点击选择或拖入文件'}</strong>
          <small>{file ? `${number(Math.ceil(file.size / 1024))} KB` :
            `GLB / glTF / FBX / OBJ / ZIP${engine ? ` · 最大 ${number(engine.max_upload_bytes / 1024 / 1024)} MB` : ''}`}</small>
        </button>
        <div className="ag-form-grid">
          <label>资产名称 <input name="name" maxLength={150} placeholder="默认使用文件名" /></label>
          <label>资产类型 <select name="asset_type" defaultValue="model">
            <option value="model">通用模型</option><option value="prop">道具</option>
            <option value="environment">场景</option><option value="character">角色</option>
          </select></label>
        </div>
        {zip && <label>ZIP 内主模型路径 <input name="model_entry" maxLength={512}
          placeholder="多个模型时填写，如 meshes/chair.obj" /></label>}
        {error && <p className="ag-notice ag-error" role="alert">{error}</p>}
      </div>
      <footer className="ag-dialog-footer"><button type="button" disabled={busy} onClick={close}>取消</button>
        <button className="ag-primary" disabled={busy} type="submit">{busy ? '正在上传…' : '上传并检查'}</button></footer>
    </form>
  </dialog>;
}

function QA({ report, before }: { report?: Report; before?: Report }) {
  const [mode, setMode] = useState('all');
  if (!report) return <section className="ag-panel"><Empty title="暂无 QA 报告">运行质量检查后，规则详情将显示在这里。</Empty></section>;
  const results = report.findings.filter(finding => mode === 'all' ||
    (mode === 'issues' ? ['FAIL', 'WARNING'].includes(finding.status) : finding.status === 'NOT_CHECKED'));
  return <section className="ag-panel">
    <header className="ag-panel-heading"><div><h2>QA 报告</h2><p>规则集 {report.ruleset_version} · {report.summary.blender_version ?
      `Blender ${report.summary.blender_version}` : 'Blender 检查未完成'} · {date(report.created_at)}</p></div>
      <select value={mode} onChange={event => setMode(event.target.value)} aria-label="筛选 QA 规则">
        <option value="all">所有规则</option><option value="issues">阻断和提醒</option><option value="unchecked">未检查</option>
      </select>
    </header>
    <div className="ag-report-totals">{Object.entries(report.summary.counts).map(([state, count]) =>
      <span key={state}><Status value={state} /><strong>{count}</strong></span>)}</div>
    {before && <p className="ag-comparison">对照父版本 {date(before.created_at)} 的报告</p>}
    <div className="ag-scroll"><table className="ag-table ag-qa-table">
      <thead><tr><th>检查项目</th><th>严重程度</th>{before && <th>处理前</th>}<th>{before ? '处理后' : '状态'}</th>
        <th>实际检测</th><th>预期</th><th>证据与建议</th></tr></thead>
      <tbody>{results.map(finding => {
        const prior = before?.findings.find(row => row.rule_id === finding.rule_id);
        return <tr key={finding.rule_id}>
          <td><strong>{finding.rule_name}</strong><small>{finding.rule_id}</small></td><td>{label[finding.severity]}</td>
          {before && <td>{prior ? <><Status value={prior.status} /><small>{format(prior.actual_value)}</small></> : '—'}</td>}
          <td><Status value={finding.status} /></td><td>{format(finding.actual_value)}</td><td>{format(finding.expected_value)}</td>
          <td><details><summary>查看</summary><p className="ag-evidence">{format(finding.evidence)}</p><p>{finding.suggestion}</p></details></td>
        </tr>;
      })}</tbody>
    </table></div>
    {!results.length && <p className="ag-inset">当前筛选无匹配规则。</p>}
  </section>;
}

type RunAction = (path: string, body?: object) => Promise<boolean>;
function History({ runs, action, busy }: { runs: Run[]; action: RunAction; busy: boolean }) {
  return <section className="ag-panel">
    <header className="ag-panel-heading"><div><h2>处理记录</h2><p>{runs.length} 个任务</p></div></header>
    {runs.length ? <div className="ag-history">{runs.map(run => <article className="ag-run" key={run.run_id}>
      <div className="ag-run-head"><div>
        <strong>{label[run.operation_type]} {run.asset_id && <a href={`#asset/${run.asset_id}`}>· {run.asset_name}</a>}</strong>
        <small className="ag-mono">{run.run_id.slice(0, 8)} · {date(run.created_at)}</small>
      </div><div className="ag-actions"><Status value={run.status} />{run.freshness === 'STALE' && <Status value="STALE" />}</div></div>
      <div className="ag-nodes">{run.nodes.map(node => <span key={node.name}><span>{label[node.name] || node.name}</span>
        <Status value={node.status} /></span>)}</div>
      {run.error_message && <pre className="ag-run-error">{run.error_message}</pre>}
      <div className="ag-actions">
        <a href={`${api}/runs/${run.run_id}/logs`} target="_blank" rel="noreferrer" className="ag-button">运行日志 ↗</a>
        {isActive(run) && <button disabled={busy || !!run.cancel_requested} onClick={() =>
          void action(`/runs/${run.run_id}/cancel`)}>{run.cancel_requested ? '正在取消' : '取消任务'}</button>}
        {['FAILED', 'CANCELED'].includes(run.status) && run.freshness !== 'STALE' &&
          <button disabled={busy} onClick={() => void action(`/runs/${run.run_id}/retry`)}>重试</button>}
        {!!Object.keys(run.parameters).length && <details className="ag-run-params"><summary>任务参数</summary>
          <pre>{JSON.stringify(run.parameters, null, 2)}</pre></details>}
      </div>
    </article>)}</div> : <Empty title="还没有任务">上传模型或在资产详情中发起检查。</Empty>}
  </section>;
}

function ModelInfo({ version, report }: { version: Version; report?: Report }) {
  const metrics = report?.summary.metrics;
  return <section className="ag-panel"><header className="ag-panel-heading"><div><h2>模型信息</h2>
    <p>{version.source_file.split('/').at(-1)}</p></div>{version.freshness === 'STALE' && <Status value="STALE" />}</header>
    <dl className="ag-info">
      {[
        ['网格对象', metrics?.objects],
        ['三角面', metrics?.triangles],
        ['顶点', metrics?.vertices],
        ['边 / 面', metrics ? `${number(metrics.edges)} / ${number(metrics.faces)}` : null],
        ['有 UV 的网格', metrics ? `${metrics.meshes.filter(mesh => mesh.uv.layers).length} / ${metrics.objects}` : null],
        ['材质', metrics?.materials],
        ['尺寸 X · Y · Z', metrics?.dimensions?.map(value => Number(value.toPrecision(4))).join(' · ')],
      ].map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{format(value)}</dd></div>)}
    </dl>
    {report && <div className="ag-report-totals ag-info-totals">
      <span><Status value="FAIL" /><strong>{report.summary.counts.FAIL}</strong></span>
      <span><Status value="WARNING" /><strong>{report.summary.counts.WARNING}</strong></span></div>}
  </section>;
}

function ProcessForm({ version, busy, action }: { version: Version; busy: boolean; action: RunAction }) {
  const [smart, setSmart] = useState(false);
  const [selection, setSelection] = useState(false);
  const [target, setTarget] = useState('');
  const stale = version.freshness === 'STALE';
  return <section className="ag-panel"><header className="ag-panel-heading">
    <div><h2>处理模型</h2><p>从 V{version.version_number} 生成新版本，导出后自动复检。</p></div></header>
    <form className="ag-form" onSubmit={event => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      void action(`/versions/${version.version_id}/process`, {
        operations: form.getAll('operations'), target_format: target || null,
        uv_angle_degrees: Number(form.get('angle') ?? 66), uv_island_margin: Number(form.get('margin') ?? 0.02),
      });
    }}>
      <fieldset disabled={busy || stale} onChange={event => {
        const form = event.currentTarget.closest('form');
        setSelection(!!form && new FormData(form).getAll('operations').length > 0);
      }}>
        <legend>处理节点</legend>
        <div className="ag-checklist">
          {['apply_transforms', 'recalculate_normals', 'smart_uv'].map(operation =>
            <label key={operation}><input type="checkbox" name="operations" value={operation}
              onChange={operation === 'smart_uv' ? event => setSmart(event.target.checked) : undefined} />{label[operation]}</label>)}
        </div>
      </fieldset>
      {smart && <><div className="ag-form-grid">
        <label>投影角度（°）<input type="number" name="angle" required min="1" max="89" step="any" defaultValue="66" /></label>
        <label>岛间距<input type="number" name="margin" required min="0" max="0.2" step="any" defaultValue="0.02" /></label>
      </div><p className="ag-notice">Smart UV 会重新展开所选网格。请在通过审核前核对展开结果。</p></>}
      <label>目标格式 <select value={target} onChange={event => setTarget(event.target.value)} disabled={stale || busy}>
        <option value="">沿用 {version.file_format}</option>
        {['GLB', 'GLTF', 'FBX', 'OBJ'].map(item => <option key={item}>{item}</option>)}
      </select></label>
      <button type="submit" className="ag-primary" disabled={stale || busy || (!selection && !target)}>开始处理</button>
    </form>
  </section>;
}

function Exports({ version, report, review, runs, busy, action }: {
  version: Version; report?: Report; review?: Review; runs: Run[]; busy: boolean; action: RunAction;
}) {
  const [decision, setDecision] = useState('APPROVED');
  const stale = version.freshness === 'STALE';
  const valid = !!report?.summary.metrics && report.summary.adapter_mode === 'BLENDER' && !report.summary.counts.FAIL;
  const approved = !stale && valid && review?.report_id === report?.report_id && review?.decision === 'APPROVED';
  const exports = runs.filter(run => run.operation_type === 'export' && run.asset_version_id === version.version_id);
  return <section className="ag-panel"><header className="ag-panel-heading">
    <div><h2>审核与导出</h2><p>V{version.version_number} · {version.file_format}</p></div>
    {review && <Status value={review.decision} />}
  </header>
    <div className="ag-export-grid">
      <form className="ag-form" onSubmit={event => {
        event.preventDefault();
        if (!report) return;
        const form = new FormData(event.currentTarget);
        void action(`/versions/${version.version_id}/review`, {
          report_id: report.report_id, reviewer: form.get('reviewer'), decision, note: form.get('note'),
        });
      }}>
        <h3>人工审核</h3>
        {review && <p>{review.reviewer} · {date(review.created_at)} {review.note ? `· ${review.note}` : ''}</p>}
        {!report && <p className="ag-notice">请先运行质量检查。</p>}
        {report && !valid && <p className="ag-notice">通过审核需要真实 Blender 检查，且阻断项为零。</p>}
        <label>审核人<input name="reviewer" required maxLength={120} placeholder="输入名称" /></label>
        <label>审核备注<textarea name="note" rows={3} maxLength={2000} /></label>
        <label>决定<select value={decision} onChange={event => setDecision(event.target.value)}>
          <option value="APPROVED">通过</option><option value="REJECTED">驳回</option>
        </select></label>
        <button disabled={busy || stale || !report || (decision === 'APPROVED' && !valid)}>保存审核</button>
      </form>
      <div className="ag-form"><h3>资产包</h3>
        <p>ZIP 包含模型、贴图依赖、Manifest、QA、处理历史与版本信息。</p>
        <button disabled={!approved || busy || exports.some(isActive)} className="ag-primary"
          onClick={() => void action(`/versions/${version.version_id}/export`)}>生成 ZIP</button>
        {exports.map(run => {
          const usable = approved && run.parameters.review_id === review?.review_id && !!run.export_file;
          return <div className="ag-actions" key={run.run_id}><Status value={run.status} /><span>{date(run.created_at)}</span>
            {usable && <a className="ag-button" href={`${api}/runs/${run.run_id}/download`}>下载 ZIP ↓</a>}</div>;
        })}
      </div>
    </div>
  </section>;
}

type Tab = 'preview' | 'qa' | 'process' | 'runs' | 'versions' | 'export';

function Detail({ asset, action, busy }: { asset: AssetDetail; action: RunAction; busy: boolean }) {
  const [selected, setSelected] = useState('');
  const [tab, setTab] = useState<Tab>('preview');
  const version = asset.versions.find(row => row.version_id === (selected || asset.current_version_id)) ?? asset.versions[0];
  const report = asset.reports.find(row => row.asset_version_id === version.version_id);
  const before = asset.reports.find(row => row.asset_version_id === version.parent_version_id);
  const review = asset.reviews.find(row => row.asset_version_id === version.version_id && row.report_id === report?.report_id);
  const waiting = asset.runs.some(run => run.asset_version_id === version.version_id && isActive(run));
  const tabs: [Tab, string][] = [['preview', '概览'], ['qa', 'QA 报告'], ['process', '模型处理'],
    ['runs', '处理记录'], ['versions', '版本历史'], ['export', '审核与导出']];
  return <>
    <div className="ag-heading"><div><a className="ag-crumb" href="#assets">资产库 /</a><h1>{asset.name}</h1>
      <p>{asset.asset_type} · {asset.versions.length} 个版本</p></div>
      <div className="ag-actions">
        <select aria-label="查看的模型版本" value={selected} onChange={event => setSelected(event.target.value)}>
          <option value="">跟随当前版本</option>
          {asset.versions.map(row => <option key={row.version_id} value={row.version_id}>
            V{row.version_number} · {row.file_format}{row.parent_version_id ? '' : ' · 原始模型'}{row.freshness === 'STALE' ? ' · 已过时' : ''}
          </option>)}
        </select>
        <button className="ag-primary" disabled={busy || waiting || version.freshness === 'STALE'} onClick={() =>
          void action(`/versions/${version.version_id}/inspect`)}>{waiting ? '任务进行中' : '运行 QA'}</button>
      </div>
    </div>
    <nav className="ag-tabs" aria-label="资产详情模块">{tabs.map(([key, name]) =>
      <button key={key} aria-current={tab === key ? 'page' : undefined} onClick={() => setTab(key)}>{name}</button>)}
    </nav>
    {tab === 'preview' && <div className="ag-detail-grid">
      <Preview key={version.version_id} version={version} waiting={waiting} error={report?.summary.preview_error} />
      <ModelInfo version={version} report={report} />
    </div>}
    {tab === 'qa' && <QA report={report} before={before} />}
    {tab === 'process' && <ProcessForm key={version.version_id} version={version} busy={busy} action={action} />}
    {tab === 'runs' && <History runs={asset.runs} action={action} busy={busy} />}
    {tab === 'versions' && <section className="ag-panel"><header className="ag-panel-heading"><div><h2>版本历史</h2>
      <p>选择版本可切换预览和 QA。切回上游会将其废弃的下游版本标记为已过时。</p></div></header>
      <div className="ag-scroll"><table className="ag-table"><thead><tr><th>版本</th><th>来源</th><th>格式 / SHA256</th>
        <th>创建时间</th><th>操作</th></tr></thead><tbody>{asset.versions.map(row => <tr key={row.version_id}>
          <td><strong>V{row.version_number}</strong>{asset.current_version_id === row.version_id &&
            <small>当前版本</small>}{row.freshness === 'STALE' && <Status value="STALE" />}</td>
          <td>{row.parent_version_id ? `V${asset.versions.find(item => item.version_id === row.parent_version_id)?.version_number}` : '原始模型'}</td>
          <td>{row.file_format}<small className="ag-mono" title={row.file_hash}>{row.file_hash.slice(0, 16)}…</small></td>
          <td>{date(row.created_at)}</td><td><div className="ag-actions">
            <button onClick={() => { setSelected(row.version_id); setTab('preview'); }}>查看</button>
            {row.freshness !== 'STALE' && row.version_id !== asset.current_version_id && <button disabled={busy} onClick={() => {
              if (window.confirm('将此版本设为当前版本？被替换的下游版本将标记为已过时。')) {
                void action(`/versions/${row.version_id}/select`).then(ok => { if (ok) setSelected(''); });
              }
            }}>设为当前</button>}</div></td>
        </tr>)}</tbody></table></div></section>}
    {tab === 'export' && <Exports key={version.version_id} version={version} report={report} review={review}
      runs={asset.runs} busy={busy} action={action} />}
  </>;
}

function App() {
  const [location, setLocation] = useState(route);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [jobs, setJobs] = useState<Run[]>([]);
  const [asset, setAsset] = useState<AssetDetail | null>(null);
  const [engine, setEngine] = useState<Engine | null>(null);
  const [opened, setOpened] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [revision, setRevision] = useState(0);
  const page = location.page;
  const id = location.id;

  useEffect(() => {
    const change = () => { setError(''); setLocation(route()); };
    window.addEventListener('hashchange', change);
    return () => window.removeEventListener('hashchange', change);
  }, []);
  useEffect(() => {
    void request<Engine>('/system').then(setEngine).catch(() => {});
  }, []);
  useEffect(() => {
    let active = true;
    let timer: number;
    const poll = async () => {
      try {
        if (id) {
          const next = await request<AssetDetail>(`/assets/${id}`);
          if (active) setAsset(next);
        } else if (page === 'jobs') {
          const next = await request<Run[]>('/runs');
          if (active) setJobs(next);
        } else {
          const next = await request<AssetRow[]>('/assets');
          if (active) setAssets(next);
        }
        if (active) setLoaded(true);
      } catch (problem) {
        if (active) setError(String(problem instanceof Error ? problem.message : problem));
      } finally {
        if (active) timer = window.setTimeout(() => void poll(), 1400);
      }
    };
    void poll();
    return () => { active = false; window.clearTimeout(timer); };
  }, [page, id, revision]);

  const action: RunAction = async (path, body) => {
    setError('');
    setBusy(true);
    try {
      await request(path, 'POST', body);
      setRevision(current => current + 1);
      return true;
    } catch (problem) {
      setError(String(problem instanceof Error ? problem.message : problem));
      return false;
    } finally {
      setBusy(false);
    }
  };
  const upload = () => setOpened(true);
  const current = asset?.asset_id === id ? asset : null;

  return <>
    <header className="ag-app-bar">
      <nav aria-label="本地工作台">{([['dashboard', '总览'], ['assets', '资产库'], ['jobs', '任务队列']] as const).map(([key, name]) =>
        <a key={key} href={`#${key}`} aria-current={page === key || (page === 'detail' && key === 'assets') ? 'page' : undefined}>{name}</a>)}</nav>
      <button className="ag-primary" onClick={upload}>＋ 上传模型</button>
    </header>
    <div className="ag-content">
      {error && <p className="ag-notice ag-error" role="alert">{error} <button onClick={() => setError('')}>关闭</button></p>}
      {page !== 'detail' && <div className="ag-heading"><div>
        <h1>{page === 'dashboard' ? '资产总览' : page === 'assets' ? '资产库' : '任务队列'}</h1>
        <p>{page === 'dashboard' ? '在一个工作台完成模型检查、处理和审核。' :
          page === 'assets' ? '浏览上传的模型与当前版本。' : '查看运行中的任务、各节点状态和 Blender 日志。'}</p>
      </div>{engine && <span className="ag-engine"><i className={engine.blender_detected ? 'available' : ''} />
        {engine.blender_detected ? '已发现本机 Blender' : '未找到 Blender'}</span>}</div>}
      {!loaded && !error && <p className="ag-inset" role="status">正在加载工作台…</p>}
      {page === 'dashboard' && loaded && <Dashboard rows={assets} engine={engine} upload={upload} />}
      {page === 'assets' && loaded && <AssetTable rows={assets} dashboard={false} upload={upload} />}
      {page === 'jobs' && loaded && <History runs={jobs} action={action} busy={busy} />}
      {page === 'detail' && current && <Detail key={current.asset_id} asset={current} action={action} busy={busy} />}
      {page === 'detail' && !current && !error && <p className="ag-inset" role="status">正在加载资产…</p>}
    </div>
    {opened && <UploadDialog engine={engine} close={() => setOpened(false)} uploaded={next => {
      setOpened(false); setAsset(next); setError(''); window.location.hash = `asset/${next.asset_id}`;
    }} />}
  </>;
}

const root = document.getElementById('assetgate-root');
if (root) createRoot(root).render(<App />);
