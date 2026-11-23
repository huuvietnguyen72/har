import { useEffect, useMemo, useRef, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, Empty, ErrorNote } from "../components/ui";
import { useLive } from "../context";
import { dataSource } from "../data";
import { POLL_MS } from "../data/api";
import { fmtHM, fmtTime } from "../format";
import { useAsync } from "../hooks";
import type { StatusLogRow } from "../types";

const MEAN = "#2a78d6"; // trung bình
const PEAK = "#eb6834"; // đỉnh
const WINDOW_MS = 120_000;
const HOUR = 3600_000;
const tip = { contentStyle: { background: "var(--card)", border: "1px solid var(--border)" } };

/** Độ cao tương đối (m) so với áp suất tham chiếu p0, công thức khí áp chuẩn. */
const altitude = (p: number, p0: number) => 44330 * (1 - Math.pow(p / p0, 1 / 5.255));

type Pt = number[];
function useLiveSensors(dev: string | null) {
  const [imu, setImu] = useState<Pt[]>([]);
  const [baro, setBaro] = useState<Pt[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loaded, setLoaded] = useState(false);
  const last = useRef({ imu: 0, baro: 0 });

  useEffect(() => {
    setImu([]); setBaro([]); setLoaded(false);
    last.current = { imu: 0, baro: 0 };
    if (!dev) return;
    let alive = true;
    const trim = (rows: Pt[]) => {
      const cut = rows.length ? rows[rows.length - 1][0] - WINDOW_MS : 0;
      return rows.filter((r) => r[0] >= cut);
    };
    const poll = async () => {
      if (document.visibilityState === "hidden") return; // tab ẩn: không tốn request
      try {
        const since = Math.min(last.current.imu || 0, last.current.baro || 0);
        const r = await dataSource.getSensors(dev, since);
        if (!alive) return;
        const newImu = r.imu.filter((x) => x[0] > last.current.imu);
        const newBaro = r.baro.filter((x) => x[0] > last.current.baro);
        if (newImu.length) last.current.imu = newImu[newImu.length - 1][0];
        if (newBaro.length) last.current.baro = newBaro[newBaro.length - 1][0];
        if (newImu.length) setImu((cur) => trim(cur.concat(newImu)));
        if (newBaro.length) setBaro((cur) => trim(cur.concat(newBaro)));
        setError(null);
      } catch (e) {
        if (alive) setError(e);
      } finally {
        if (alive) setLoaded(true);
      }
    };
    void poll();
    const id = window.setInterval(poll, POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [dev]);
  return { imu, baro, error, loaded };
}

function TimeChart({ data, xFmt, height = 210, children, yUnit, yDomain, yWidth = 52 }: {
  data: object[]; xFmt: (t: number) => string; height?: number; children: React.ReactNode;
  yUnit?: string; yDomain?: React.ComponentProps<typeof YAxis>["domain"]; yWidth?: number;
}) {
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ right: 12, left: 0, top: 6 }}>
          <CartesianGrid stroke="var(--grid)" />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={xFmt} stroke="var(--muted)" fontSize={12} minTickGap={40} />
          <YAxis domain={yDomain ?? ["auto", "auto"]} stroke="var(--muted)" fontSize={12} unit={yUnit} width={yWidth} allowDecimals />
          <Tooltip labelFormatter={(t: number) => xFmt(t)} {...tip} />
          {children}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function Sensors() {
  const { statuses, selectedDev } = useLive();
  const st = selectedDev ? statuses[selectedDev] : undefined;
  const live = useLiveSensors(selectedDev);

  const imuRows = useMemo(() => live.imu.map(([t, svm, svmMax, gyro]) => ({ t, svm, svmMax, gyro })), [live.imu]);
  const altRows = useMemo(() => {
    if (!live.baro.length) return [];
    const head = live.baro.slice(0, 5).map((r) => r[1]);
    const p0 = head.reduce((s, v) => s + v, 0) / head.length; // mốc 0 m: đầu cửa sổ 2 phút
    return live.baro.map(([t, p]) => ({ t, alt: Math.round(altitude(p, p0) * 100) / 100 }));
  }, [live.baro]);
  const lastT = imuRows.length ? imuRows[imuRows.length - 1].t : null;
  const stale = lastT != null && Date.now() - lastT > 20_000;

  const [to, setTo] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setTo(Date.now()), 60_000);
    return () => window.clearInterval(id);
  }, []);
  const hist = useAsync<StatusLogRow[]>(
    () => (selectedDev ? dataSource.getStatusHistory(selectedDev, to - 24 * HOUR, to) : Promise.resolve([])), [selectedDev, to]);
  const histRows = useMemo(() => (hist.data ?? []).filter((r) => r.svm_mean != null || r.p_hpa != null), [hist.data]);
  const histDot = histRows.length < 30 ? { r: 2.5 } : false; // ít điểm (mới bật): hiện chấm để thấy được

  return (
    <div className="grid">
      <Card className="span-all" title={<>Trực tiếp · 2 phút gần nhất <span className="muted">· {st?.alias || selectedDev || "—"}</span></>}
        actions={<span className="muted small">
          {lastT ? <>Mẫu mới nhất {fmtTime(lastT)}{stale ? " · bộ đeo không gửi dữ liệu" : ""}</> : "Chưa có dữ liệu"} · điểm 5 Hz
        </span>}>
        <ErrorNote error={live.error} />
        {!imuRows.length && !altRows.length ? (
          <Empty>{live.loaded ? "Chưa có dữ liệu cảm biến: bộ đeo offline hoặc Pi chưa gửi bản cập nhật mới." : "Đang tải…"}</Empty>
        ) : (
          <div className="sensor-grid">
            <div>
              <h4 className="chart-title">Gia tốc (độ lớn SVM, g)</h4>
              <TimeChart data={imuRows} xFmt={fmtTime} yDomain={[0, (max: number) => Math.max(2, Math.ceil(max))]} yUnit=" g">
                <ReferenceLine y={1} stroke="var(--muted)" strokeDasharray="4 4" />
                <Legend verticalAlign="top" height={24} iconType="plainline" />
                <Line name="Trung bình 0,2 s" dataKey="svm" stroke={MEAN} dot={false} strokeWidth={1.8} isAnimationActive={false} />
                <Line name="Đỉnh 0,2 s" dataKey="svmMax" stroke={PEAK} dot={false} strokeWidth={1.2} isAnimationActive={false} />
              </TimeChart>
              <p className="small muted">Đứng yên ≈ 1 g (đường nét đứt). Đi bộ dao động quanh 1 g; té có đỉnh vài g.</p>
            </div>
            <div>
              <h4 className="chart-title">Con quay (độ lớn vận tốc góc, °/s)</h4>
              <TimeChart data={imuRows} xFmt={fmtTime} yDomain={[0, "auto"]} yUnit="°/s" yWidth={60}>
                <Line name="Con quay" dataKey="gyro" stroke={MEAN} dot={false} strokeWidth={1.8} isAnimationActive={false} />
              </TimeChart>
              <p className="small muted">Gần 0 khi ngồi, nằm yên; tăng khi đi, xoay người, cúi xuống.</p>
            </div>
            <div>
              <h4 className="chart-title">Độ cao tương đối (m, từ áp suất BMP280)</h4>
              <TimeChart data={altRows} xFmt={fmtTime} yUnit=" m" yDomain={[(min: number) => Math.min(-0.5, Math.floor(min)), (max: number) => Math.max(0.5, Math.ceil(max))]}>
                <ReferenceLine y={0} stroke="var(--muted)" strokeDasharray="4 4" />
                <Line name="Độ cao" dataKey="alt" stroke={MEAN} dot={false} strokeWidth={1.8} isAnimationActive={false} />
              </TimeChart>
              <p className="small muted">Mốc 0 m là đầu cửa sổ 2 phút. Lên một tầng cầu thang ≈ +3 m; dao động ±0,3 m là nhiễu.</p>
            </div>
          </div>
        )}
      </Card>

      <Card className="span-all" title="24 giờ qua · mỗi phút một điểm">
        <ErrorNote error={hist.error} />
        {histRows.length < 2 ? (
          <Empty>{hist.loading ? "Đang tải…" : "Chưa đủ dữ liệu lịch sử (cần bản Pi mới gửi số liệu theo phút)."}</Empty>
        ) : (
          <div className="sensor-grid">
            <div>
              <h4 className="chart-title">Gia tốc (g)</h4>
              <TimeChart data={histRows} xFmt={fmtHM} yDomain={[0, (max: number) => Math.max(2, Math.ceil(max))]} yUnit=" g">
                <Legend verticalAlign="top" height={24} iconType="plainline" />
                <Line name="Trung bình 1 phút" dataKey="svm_mean" stroke={MEAN} dot={histDot} strokeWidth={1.8} isAnimationActive={false} connectNulls={false} />
                <Line name="Đỉnh 1 phút" dataKey="svm_max" stroke={PEAK} dot={histDot} strokeWidth={1.2} isAnimationActive={false} connectNulls={false} />
              </TimeChart>
            </div>
            <div>
              <h4 className="chart-title">Con quay trung bình (°/s)</h4>
              <TimeChart data={histRows} xFmt={fmtHM} yDomain={[0, "auto"]} yUnit="°/s" yWidth={60}>
                <Line name="Con quay" dataKey="gyro_mean" stroke={MEAN} dot={histDot} strokeWidth={1.8} isAnimationActive={false} connectNulls={false} />
              </TimeChart>
            </div>
            <div>
              <h4 className="chart-title">Áp suất khí quyển (hPa)</h4>
              <TimeChart data={histRows} xFmt={fmtHM} yUnit="" yWidth={64}>
                <Line name="Áp suất" dataKey="p_hpa" stroke={MEAN} dot={histDot} strokeWidth={1.8} isAnimationActive={false} connectNulls={false} />
              </TimeChart>
              <p className="small muted">Áp suất đổi theo thời tiết trong ngày; lên xuống cầu thang chỉ làm đổi ~0,1–0,4 hPa trong vài giây.</p>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
