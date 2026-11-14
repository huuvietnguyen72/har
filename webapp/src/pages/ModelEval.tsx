import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend as RLegend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, Empty, ErrorNote, Stat } from "../components/ui";
import { useLive } from "../context";
import { dataSource } from "../data";
import { fmtHM, fmtNum, fmtPct } from "../format";
import { useAsync } from "../hooks";
import { LABEL_VI, STAGE_VI } from "../labels";
import type { Experiment, MetricsResponse, StatusLogRow } from "../types";

const DATASET_URL = import.meta.env.VITE_DATASET_URL as string | undefined;
const METHOD_VI: Record<string, string> = { threshold: "Ngưỡng (ESP32)", model: "Model (Pi)", combined: "Kết hợp" };
const PAIRS: [string, string, string][] = [["A1", "A2", "Random Forest"], ["B1", "B2", "1D-CNN"]];

function Heatmap({ exp }: { exp: Experiment }) {
  if (!exp.confusion) return <Empty>Thí nghiệm này không có ma trận nhầm lẫn.</Empty>;
  const { labels, matrix } = exp.confusion;
  const rowSum = matrix.map((r) => r.reduce((s, v) => s + v, 0) || 1);
  return (
    <div className="table-wrap">
      <table className="heatmap">
        <thead>
          <tr>
            <th className="corner">Thật \ Dự đoán</th>
            {labels.map((l) => <th key={l}>{LABEL_VI[l as keyof typeof LABEL_VI] ?? l}</th>)}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={labels[i]}>
              <th>{LABEL_VI[labels[i] as keyof typeof LABEL_VI] ?? labels[i]}</th>
              {row.map((v, j) => {
                const p = v / rowSum[i];
                return (
                  <td key={j} title={`${v} cửa sổ (${(p * 100).toFixed(1)}% của hàng)`}
                    style={{ background: i === j ? `rgba(15,118,110,${0.12 + p * 0.85})` : p > 0 ? `rgba(220,38,38,${0.08 + p * 1.6})` : undefined,
                      color: p > 0.55 ? "#fff" : undefined }}>
                    {v || ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ModelEval() {
  const { selectedDev } = useLive();
  const m = useAsync<MetricsResponse>(() => dataSource.getMetrics(), []);
  const to = useMemo(() => Date.now(), []);
  const hist = useAsync<StatusLogRow[]>(
    () => (selectedDev ? dataSource.getStatusHistory(selectedDev, to - 24 * 3600_000, to) : Promise.resolve([])), [selectedDev]);
  const exps = (m.data?.experiments ?? []).filter((e) => e.experiment !== "D");
  const d = m.data?.experiments.find((e) => e.experiment === "D");
  const [sel, setSel] = useState<string | null>(null);
  const current = exps.find((e) => e.experiment === sel) ?? exps.find((e) => e.experiment === "A2") ?? exps[0];
  const sys = m.data?.system?.[0];
  const anySynthetic = m.data?.experiments.some((e) => e.extra?.synthetic || e.extra?.mock);
  const best = exps.reduce<Experiment | null>((b, e) => ((e.macro_f1 ?? 0) > (b?.macro_f1 ?? -1) ? e : b), null);

  const pairData = PAIRS.map(([a, b, name]) => {
    const ea = exps.find((e) => e.experiment === a);
    const eb = exps.find((e) => e.experiment === b);
    if (!ea || !eb) return null;
    const labels = [...new Set([...Object.keys(ea.f1_per_class ?? {}), ...Object.keys(eb.f1_per_class ?? {})])];
    return {
      name, a, b,
      rows: labels.map((l) => ({ label: LABEL_VI[l as keyof typeof LABEL_VI] ?? l, imu: ea.f1_per_class?.[l] ?? 0, baro: eb.f1_per_class?.[l] ?? 0 })),
    };
  }).filter(Boolean) as { name: string; a: string; b: string; rows: { label: string; imu: number; baro: number }[] }[];

  const battery = (hist.data ?? []).filter((r) => r.battery_v != null).map((r) => ({ t: r.t, v: r.battery_v, pct: r.battery_pct }));

  return (
    <div className="grid">
      <ErrorNote error={m.error} />
      {anySynthetic && (
        <div className="span-all warn-note">
          Một số kết quả được sinh từ dữ liệu giả lập hoặc dữ liệu mẫu — chỉ để thử giao diện, không phải số liệu thật.
        </div>
      )}

      <Card className="span-all" title="Model đang chạy">
        <div className="stats">
          {Object.entries(m.data?.running_models ?? {}).map(([dev, model]) => (
            <Stat key={dev} label={dev} value={<code>{model ?? "—"}</code>} />
          ))}
          {best && <Stat label="Macro-F1 tốt nhất" value={fmtNum(best.macro_f1, 3)} sub={`${best.experiment} · ${best.model}`} />}
          {sys?.battery_hours != null && <Stat label="Thời lượng pin đo được" value={`${fmtNum(sys.battery_hours, 1)} giờ`} />}
          {sys?.packet_loss != null && <Stat label="Tỉ lệ mất gói MQTT" value={fmtPct(sys.packet_loss, 2)} sub={sys.day} />}
        </div>
        {DATASET_URL && <p className="small"><a className="link" href={DATASET_URL} target="_blank" rel="noreferrer">Tải dataset thô (nén) →</a></p>}
      </Card>

      <Card className="span-all" title="So sánh thí nghiệm" actions={<span className="muted small">Đánh giá chia theo người (GroupKFold)</span>}>
        {exps.length === 0 ? <Empty>Chưa có kết quả. Chạy ml/run_experiments.py rồi push_metrics.py.</Empty> : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Thí nghiệm</th><th>Model</th><th>Đặc trưng</th><th>Cửa sổ</th><th>Accuracy</th><th>Macro-F1</th>
                  <th>F1 lên CT</th><th>F1 xuống CT</th><th>F1 té</th><th>Cửa sổ / người</th></tr>
              </thead>
              <tbody>
                {exps.map((e) => (
                  <tr key={e.experiment} className={current?.experiment === e.experiment ? "selected" : ""}
                    onClick={() => setSel(e.experiment)} style={{ cursor: "pointer" }}>
                    <td data-th="Thí nghiệm"><strong>{e.experiment}</strong> {e.extra?.synthetic && <Badge tone="warn">giả lập</Badge>}</td>
                    <td data-th="Model"><code>{e.model}</code></td>
                    <td data-th="Đặc trưng">{e.features === "imu+baro" ? "IMU + BMP280" : "Chỉ IMU"}</td>
                    <td data-th="Cửa sổ">{e.window_s} s</td>
                    <td data-th="Accuracy">{fmtNum(e.accuracy, 3)}</td>
                    <td data-th="Macro-F1"><strong>{fmtNum(e.macro_f1, 3)}</strong></td>
                    <td data-th="F1 lên CT">{fmtNum(e.f1_per_class?.stairs_up, 2)}</td>
                    <td data-th="F1 xuống CT">{fmtNum(e.f1_per_class?.stairs_down, 2)}</td>
                    <td data-th="F1 té">{fmtNum(e.f1_per_class?.fall, 2)}</td>
                    <td data-th="Cửa sổ / người">{e.n_windows ?? "—"} / {e.n_subjects ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {pairData.map((p) => (
        <Card key={p.name} title={`${p.name}: F1 từng lớp, chỉ IMU (${p.a}) vs IMU + BMP280 (${p.b})`}>
          <div className="chart">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={p.rows} margin={{ right: 8 }}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="label" stroke="var(--muted)" fontSize={11} interval={0} angle={-25} textAnchor="end" height={60} />
                <YAxis domain={[0, 1]} stroke="var(--muted)" fontSize={12} />
                <Tooltip formatter={(v: number) => v.toFixed(3)} contentStyle={{ background: "var(--card)", border: "1px solid var(--border)" }} />
                <RLegend />
                <Bar dataKey="imu" name="Chỉ IMU" fill="#94a3b8" radius={[3, 3, 0, 0]} />
                <Bar dataKey="baro" name="IMU + BMP280" fill="#0f766e" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      ))}

      {current && (
        <Card className="span-all" title={`Ma trận nhầm lẫn · ${current.experiment} (${current.model})`}
          actions={<span className="muted small">Bấm một dòng ở bảng trên để đổi thí nghiệm</span>}>
          <Heatmap exp={current} />
          {current.extra?.feature_importance && (
            <p className="small muted">Đặc trưng quan trọng nhất: {Object.keys(current.extra.feature_importance).slice(0, 6).join(", ")}</p>
          )}
        </Card>
      )}

      {d?.extra?.methods && (
        <Card className="span-all" title="Thí nghiệm D · phát hiện té: ngưỡng vs model vs kết hợp">
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Phương pháp</th><th>Độ nhạy</th><th>Báo động giả / giờ</th><th>Độ đặc hiệu (phiên)</th><th>Độ trễ phát hiện (trung vị)</th></tr></thead>
              <tbody>
                {Object.entries(d.extra.methods as Record<string, any>).map(([k, v]) => (
                  <tr key={k}>
                    <td data-th="Phương pháp"><strong>{METHOD_VI[k] ?? k}</strong></td>
                    <td data-th="Độ nhạy">{fmtPct(v.sensitivity, 1)}</td>
                    <td data-th="Báo động giả / giờ">{fmtNum(v.false_alarms_per_hour, 2)}</td>
                    <td data-th="Độ đặc hiệu">{fmtPct(v.specificity_recordings, 1)}</td>
                    <td data-th="Độ trễ">{v.detect_delay_ms_median != null ? `${(v.detect_delay_ms_median / 1000).toFixed(1)} s` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">Đo trên {fmtNum(d.extra.adl_hours, 2)} giờ sinh hoạt không té, {d.n_subjects} người, leave-one-subject-out. Độ trễ chưa gồm 10 s chờ hủy trên thiết bị.</p>
        </Card>
      )}

      <Card title="Độ trễ từng chặng">
        {sys?.latency && Object.keys(sys.latency).length ? (
          <table className="table compact">
            <thead><tr><th>Chặng</th><th>Trung vị</th><th>p95</th></tr></thead>
            <tbody>
              {Object.entries(sys.latency).map(([k, v]) => (
                <tr key={k}><td>{STAGE_VI[k] ?? k}</td><td>{fmtNum(v.median, 1)} ms</td><td>{fmtNum(v.p95, 1)} ms</td></tr>
              ))}
            </tbody>
          </table>
        ) : <Empty>Chưa có số liệu độ trễ (Pi gửi mỗi 10 phút).</Empty>}
        {sys && <p className="small muted">Ngày {sys.day} · {sys.dev} · {sys.packets ?? "—"} gói</p>}
      </Card>

      <Card title="Điện áp pin 24 giờ qua">
        {battery.length > 1 ? (
          <div className="chart">
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={battery} margin={{ right: 8 }}>
                <CartesianGrid stroke="var(--grid)" />
                <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={fmtHM} stroke="var(--muted)" fontSize={12} />
                <YAxis domain={[3.2, 4.25]} stroke="var(--muted)" fontSize={12} unit=" V" width={56} />
                <Tooltip labelFormatter={(t: number) => fmtHM(t)} formatter={(v: number) => [`${v.toFixed(2)} V`, "Pin"]}
                  contentStyle={{ background: "var(--card)", border: "1px solid var(--border)" }} />
                <Line type="monotone" dataKey="v" stroke="#0f766e" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : <Empty>Chưa đủ dữ liệu pin.</Empty>}
      </Card>
    </div>
  );
}
