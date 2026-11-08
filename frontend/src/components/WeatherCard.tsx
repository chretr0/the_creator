import { useEffect, useState } from "react";
import { compass, describeWeather, loadForecast, type ForecastHour, type PointForecast, type WeatherKind } from "../lib/context";
import Icon, { type IconName } from "./Icon";

const ICON: Record<WeatherKind, IconName> = {
  clear: "sun",
  partly: "cloudSun",
  cloudy: "cloud",
  fog: "fog",
  drizzle: "drizzle",
  rain: "rain",
  snow: "snow",
  storm: "storm",
};

function weatherIcon(code: number | null, isDay = true): IconName {
  const { kind } = describeWeather(code);
  if (!isDay && kind === "clear") return "moon";
  if (!isDay && kind === "partly") return "cloudMoon";
  return ICON[kind];
}

const deg = (v: number | null) => (v === null ? "—" : `${Math.round(v)}°`);
const hourOf = (iso: string) => iso.slice(11, 16);
const dayName = (date: string, i: number) =>
  i === 0 ? "Today" : i === 1 ? "Tomorrow" : new Date(`${date}T12:00:00Z`).toLocaleDateString(undefined, { weekday: "long", timeZone: "UTC" });

/** Live conditions at the selected point, fetched as soon as the location is picked. */
export default function WeatherCard({ latitude, longitude }: { latitude: number; longitude: number }) {
  const [forecast, setForecast] = useState<PointForecast | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setForecast(null);
    setError(false);
    loadForecast(latitude, longitude, ctrl.signal)
      .then(setForecast)
      .catch(() => !ctrl.signal.aborted && setError(true));
    return () => ctrl.abort();
  }, [latitude, longitude, attempt]);

  if (error)
    return (
      <div className="insight-card weather-card">
        <p className="muted small">The forecast couldn’t be loaded.</p>
        <button className="chip" onClick={() => setAttempt((n) => n + 1)}>Try again</button>
      </div>
    );
  if (!forecast)
    return (
      <div className="insight-card weather-card loading" aria-busy="true">
        <div className="skeleton" style={{ height: 56, width: "55%" }} />
        <div className="skeleton" style={{ height: 64, marginTop: 14 }} />
        <div className="skeleton" style={{ height: 40, marginTop: 14 }} />
      </div>
    );

  const now = forecast.current;
  const sky = describeWeather(now.code);
  const winds = forecast.hours.map((h) => h.wind100m).filter((v): v is number => v !== null);
  const windMean = winds.length ? winds.reduce((a, b) => a + b, 0) / winds.length : null;
  const windMax = winds.length ? Math.max(...winds) : null;
  const rainChance = Math.max(0, ...forecast.hours.map((h) => h.precipProb ?? 0));

  return (
    <div className={`insight-card weather-card ${now.isDay ? "day" : "night"}`}>
      <div className="weather-now">
        <Icon name={weatherIcon(now.code, now.isDay)} size={46} className="weather-glyph" />
        <div className="weather-temp">
          <strong>{deg(now.tempC)}</strong>
          <span>{sky.label}</span>
        </div>
        <dl className="weather-facts">
          <div><dt>Feels like</dt><dd>{deg(now.feelsLikeC)}</dd></div>
          <div><dt>Humidity</dt><dd>{now.humidity === null ? "—" : `${Math.round(now.humidity)}%`}</dd></div>
          <div>
            <dt>Wind</dt>
            <dd>
              {now.windDirection !== null && (
                <Icon name="navigation" size={11} className="wind-arrow" style={{ transform: `rotate(${now.windDirection + 180}deg)` }} />
              )}
              {now.windSpeed === null ? "—" : `${now.windSpeed.toFixed(1)} m/s`}
              {now.windDirection !== null && <span className="muted"> {compass(now.windDirection)}</span>}
            </dd>
          </div>
        </dl>
      </div>

      {forecast.hours.length > 1 && <HourlyCurve hours={forecast.hours} />}

      <ul className="weather-days">
        {forecast.days.map((d, i) => (
          <li key={d.date}>
            <span className="day-name">{dayName(d.date, i)}</span>
            <Icon name={weatherIcon(d.code)} size={18} />
            <span className="day-range">
              <strong>{deg(d.maxC)}</strong> <span className="muted">{deg(d.minC)}</span>
            </span>
            <span className="muted day-rain">{d.precipMm ? `${d.precipMm.toFixed(1)} mm` : "Dry"}</span>
          </li>
        ))}
      </ul>

      <div className="weather-strip">
        <span><Icon name="wind" size={14} /> Wind at 100 m <strong>{windMean === null ? "—" : `${windMean.toFixed(1)} m/s`}</strong>{windMax !== null && <span className="muted">· peak {windMax.toFixed(1)}</span>}</span>
        <span><Icon name="water" size={14} /> Rain chance today <strong>{rainChance}%</strong></span>
      </div>
      <p className="weather-time muted">Local time {hourOf(forecast.time)}</p>
    </div>
  );
}

/** Next-24-hour temperature curve, with rain chance as faint bars behind it. */
function HourlyCurve({ hours }: { hours: ForecastHour[] }) {
  const temps = hours.map((h) => h.tempC);
  const known = temps.filter((t): t is number => t !== null);
  if (known.length < 2) return null;
  const lo = Math.min(...known);
  const hi = Math.max(...known);
  const W = 300;
  const H = 74;
  const top = 16;
  const bottom = 16;
  const x = (i: number) => (i / (hours.length - 1)) * W;
  const y = (t: number) => top + (1 - (t - lo) / (hi - lo || 1)) * (H - top - bottom);
  const pts = hours.map((h, i) => (h.tempC === null ? null : [x(i), y(h.tempC)] as const)).filter(Boolean) as (readonly [number, number])[];
  const line = pts.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join(" ");
  const area = `${line} L${pts[pts.length - 1][0].toFixed(1)},${H - bottom} L${pts[0][0].toFixed(1)},${H - bottom} Z`;
  const iMax = temps.indexOf(hi);
  const iMin = temps.indexOf(lo);
  const ticks = [0, 6, 12, 18].filter((i) => i < hours.length);
  return (
    <figure className="hourly">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label={`Next 24 hours: ${Math.round(lo)}° to ${Math.round(hi)}°`}>
        <defs>
          <linearGradient id="hourly-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="currentColor" stopOpacity="0.28" />
            <stop offset="1" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>
        {hours.map((h, i) =>
          h.precipProb ? (
            <rect key={h.time} className="rain-bar" x={x(i) - 4} width={8} y={H - bottom - (h.precipProb / 100) * (H - top - bottom)} height={(h.precipProb / 100) * (H - top - bottom)} rx={2}>
              <title>{`${hourOf(h.time)} · ${h.precipProb}% chance of rain`}</title>
            </rect>
          ) : null,
        )}
        <path d={area} fill="url(#hourly-fill)" />
        <path d={line} className="temp-line" />
        {[iMax, iMin].map((i, k) =>
          temps[i] === null ? null : (
            <g key={k}>
              <circle cx={x(i)} cy={y(temps[i]!)} r={3} className="temp-dot" />
              <text x={Math.min(W - 14, Math.max(14, x(i)))} y={y(temps[i]!) - 6} className="temp-label">
                {deg(temps[i])}
              </text>
            </g>
          ),
        )}
        {ticks.map((i) => (
          <text key={i} x={Math.max(10, x(i))} y={H - 2} className="tick">
            {i === 0 ? "Now" : hourOf(hours[i].time)}
          </text>
        ))}
      </svg>
    </figure>
  );
}
