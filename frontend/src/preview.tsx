import { useEffect, useRef, useState } from 'react';
import {
  AmbientLight, Box3, Box3Helper, BufferGeometry, Color, DirectionalLight, GridHelper, Material,
  Mesh, Object3D, PerspectiveCamera, Scene, Texture, Vector3, WebGLRenderer,
} from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

import { api, type Version } from './model';

function disposeModel(model: Object3D) {
  const geometries = new Set<BufferGeometry>();
  const materials = new Set<Material>();
  const textures = new Set<Texture>();
  model.traverse(object => {
    if (!(object instanceof Mesh)) return;
    geometries.add(object.geometry);
    for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
      materials.add(material);
      for (const parameter of Object.values(material)) {
        if (parameter instanceof Texture) textures.add(parameter);
      }
    }
  });
  for (const resource of [...textures, ...materials, ...geometries]) resource.dispose();
}

export function Preview({ version, waiting, error }: { version: Version; waiting: boolean; error?: string | null }) {
  const container = useRef<HTMLDivElement>(null);
  const helpers = useRef<{ grid: GridHelper; box: Box3Helper | null; reset: () => void; render: () => void }>(null);
  const visibility = useRef({ grid: true, box: false });
  const [grid, setGrid] = useState(true);
  const [box, setBox] = useState(false);
  const [phase, setPhase] = useState('idle');
  const [message, setMessage] = useState('');
  const versionId = version.version_id;
  const previewFile = version.preview_file;

  useEffect(() => {
    const host = container.current;
    if (!host || !previewFile) return;
    setPhase('loading');
    setMessage('');
    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setPhase('error');
      setMessage('此浏览器无法创建 WebGL 2 上下文。');
      return;
    }
    const scene = new Scene();
    scene.background = new Color('#20242c');
    const camera = new PerspectiveCamera(42, 1, 0.001, 1000);
    camera.position.set(3, 2, 3);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    host.appendChild(renderer.domElement);
    renderer.domElement.setAttribute('aria-label', '交互式三维预览');
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.screenSpacePanning = true;
    scene.add(new AmbientLight('#ffffff', 1.6));
    const key = new DirectionalLight('#fff4de', 2.6);
    key.position.set(4, 5, 3);
    const fill = new DirectionalLight('#9ec2ff', 1.3);
    fill.position.set(-4, 2, -4);
    scene.add(key, fill);
    let floor = new GridHelper(6, 24, '#616a79', '#353d49');
    scene.add(floor);
    let outline: Box3Helper | null = null;
    let model: Object3D | null = null;
    let alive = true;
    const render = () => renderer.render(scene, camera);
    const resize = () => {
      const { clientWidth, clientHeight } = host;
      if (!clientWidth || !clientHeight) return;
      camera.aspect = clientWidth / clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(clientWidth, clientHeight, false);
      render();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    controls.addEventListener('change', render);
    resize();
    const abort = new AbortController();
    void fetch(`${api}/versions/${versionId}/preview`, { signal: abort.signal, cache: 'no-store' })
      .then(async response => {
        if (!response.ok) throw new Error('无法获取 GLB 预览文件。');
        const data = await response.arrayBuffer();
        return new GLTFLoader().parseAsync(data, '');
      })
      .then(gltf => {
        if (!alive) {
          disposeModel(gltf.scene);
          return;
        }
        model = gltf.scene;
        scene.add(model);
        const bounds = new Box3().setFromObject(model);
        if (bounds.isEmpty()) throw new Error('预览文件没有可用的包围盒。');
        const center = bounds.getCenter(new Vector3());
        const size = Math.max(bounds.getSize(new Vector3()).length(), 0.00001);
        scene.remove(floor);
        floor.dispose();
        floor = new GridHelper(size * 3, 24, '#5b6476', '#363f4b');
        floor.position.set(center.x, bounds.min.y - size * 0.002, center.z);
        floor.visible = visibility.current.grid;
        outline = new Box3Helper(bounds, '#fbc16a');
        outline.visible = visibility.current.box;
        scene.add(floor, outline);
        const reset = () => {
          const ratio = Math.max(1, 1 / camera.aspect);
          camera.near = size / 1000;
          camera.far = size * 500;
          camera.updateProjectionMatrix();
          camera.position.copy(center).addScaledVector(new Vector3(1, 0.72, 1).normalize(), size * 2.0 * ratio);
          controls.target.copy(center);
          controls.update();
          render();
        };
        helpers.current = { grid: floor, box: outline, reset, render };
        reset();
        setPhase('ready');
      })
      .catch((exception: unknown) => {
        if (!alive) return;
        setMessage(exception instanceof Error ? exception.message : '预览加载失败。');
        setPhase('error');
      });
    return () => {
      alive = false;
      abort.abort();
      observer.disconnect();
      controls.dispose();
      if (model) disposeModel(model);
      floor.dispose();
      outline?.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
      helpers.current = null;
    };
  }, [versionId, previewFile]);

  function toggle(which: 'grid' | 'box') {
    const next = !visibility.current[which];
    visibility.current[which] = next;
    if (which === 'grid') setGrid(next);
    else setBox(next);
    const view = helpers.current;
    if (view?.[which]) view[which].visible = next;
    view?.render();
  }

  const caption = !previewFile ? (waiting ? 'Blender 正在准备预览…' : error || '此版本暂无可显示的预览。') :
    phase === 'error' ? message : '正在载入 GLB…';

  return <section className="ag-panel ag-viewer" aria-label="3D 预览">
    <header className="ag-panel-heading">
      <div><h2>3D 预览</h2><p>V{version.version_number} · {version.file_format}</p></div>
      <div className="ag-actions">
        <button disabled={phase !== 'ready' || !previewFile} aria-pressed={grid} onClick={() => toggle('grid')}>网格</button>
        <button disabled={phase !== 'ready' || !previewFile} aria-pressed={box} onClick={() => toggle('box')}>包围盒</button>
        <button disabled={phase !== 'ready' || !previewFile} onClick={() => helpers.current?.reset()}>复位视角</button>
      </div>
    </header>
    <div className="ag-viewport">
      <div className="ag-canvas" ref={container} />
      {(!previewFile || phase !== 'ready') && <div className="ag-viewport-placeholder"><span aria-hidden="true">◇</span><p>{caption}</p></div>}
    </div>
    <div className="ag-viewer-help">拖动旋转 · 滚轮缩放 · 右键拖动平移</div>
  </section>;
}
