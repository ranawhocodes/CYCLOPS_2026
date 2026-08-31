import { useStore } from "../store";
import { Empty } from "./IntensityPanel";

export function CamViewer() {
  const frameUrl = useStore((s) => s.frameUrl);
  const cam = useStore((s) => s.classify?.cam);
  const show = useStore((s) => s.showCam);
  const opacity = useStore((s) => s.camOpacity);
  const setShow = useStore((s) => s.setShowCam);
  const setOpacity = useStore((s) => s.setCamOpacity);

  if (!frameUrl) return <Empty label="Why this estimate" hint="No frame loaded" />;

  return (
    <section className="panel" aria-label="Model attention">
      <h2 className="panel-title">
        Why this estimate
        <span className="synthetic-tag" title="Imagery in this build is synthetic">
          SYNTHETIC IMAGERY
        </span>
      </h2>

      <div className="cam-stage">
        <img src={frameUrl} alt="Infrared satellite frame" className="cam-base" />
        {cam && show && (
          <img
            src={`data:image/png;base64,${cam.data}`}
            alt="Model attention heat map overlaid on the infrared frame"
            className="cam-overlay"
            style={{ opacity }}
          />
        )}
      </div>

      <div className="cam-controls">
        <button onClick={() => setShow(!show)} aria-pressed={show} className="btn">
          {show ? "Hide attention" : "Show attention"}
        </button>
        <label className="slider">
          <span>Overlay</span>
          <input type="range" min={0} max={1} step={0.05} value={opacity}
                 disabled={!show}
                 onChange={(e) => setOpacity(Number(e.target.value))} />
        </label>
      </div>

      <p className="cam-caption">
        {cam?.note ?? "Brighter regions increased the estimated wind speed."}
        {cam?.expected_focus && (
          <>
            {" "}At this stage attention should be <strong>{cam.expected_focus}</strong>.
          </>
        )}
      </p>
    </section>
  );
}
