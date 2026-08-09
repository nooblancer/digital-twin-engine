'use client';

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { useStore } from '@/store';

interface SensorChartProps {
  sensorId: string;
}

function formatTimestamp(timestamp: number): string {
  const now = Date.now();
  const secondsAgo = Math.round((now - timestamp) / 1000);
  if (secondsAgo <= 0) return 'now';
  if (secondsAgo < 60) return `${secondsAgo}s ago`;
  const minutesAgo = Math.round(secondsAgo / 60);
  return `${minutesAgo}m ago`;
}

export function SensorChart({ sensorId }: SensorChartProps) {
  const data = useStore((state) => state.sensorData[sensorId] ?? []);

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={250}>
        <LineChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
          <CartesianGrid
            stroke="hsl(220, 10%, 20%)"
            strokeDasharray="3 3"
          />
          <XAxis
            dataKey="timestamp"
            tickFormatter={formatTimestamp}
            stroke="hsl(215, 12%, 58%)"
            tick={{ fontSize: 11 }}
          />
          <YAxis
            stroke="hsl(215, 12%, 58%)"
            tick={{ fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'hsl(220, 13%, 9%)',
              border: '1px solid hsl(220, 12%, 18%)',
              borderRadius: '6px',
              color: 'hsl(210, 20%, 92%)',
            }}
            labelFormatter={(label) => formatTimestamp(Number(label))}
          />
          <Legend />
          <Line
            type="monotone"
            dataKey="raw"
            name="Raw"
            stroke="hsl(215, 20%, 55%)"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="predicted"
            name="Predicted"
            stroke="hsl(192, 40%, 55%)"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="corrected"
            name="Corrected"
            stroke="hsl(150, 35%, 50%)"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
