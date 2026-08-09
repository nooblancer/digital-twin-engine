'use client';

import { useStore } from '@/store';
import type { SensorStatus } from '@/types';

const statusBorderColor: Record<SensorStatus, string> = {
  healthy: 'border-l-[hsl(var(--status-healthy))]',
  warning: 'border-l-[hsl(var(--status-warning))]',
  critical: 'border-l-[hsl(var(--status-critical))]',
};

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function SensorHealthCards() {
  const sensorHealth = useStore((state) => state.sensorHealth);

  const sensors = Object.values(sensorHealth);

  if (sensors.length === 0) {
    return (
      <div className="flex items-center justify-center p-4 text-sm text-muted-foreground">
        No sensors connected
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
      {sensors.map((sensor) => (
        <div
          key={sensor.sensor_id}
          className={`border-l-4 ${statusBorderColor[sensor.status]} bg-card rounded-md p-3`}
        >
          <p className="text-sm font-semibold text-card-foreground truncate">
            {sensor.sensor_id}
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            {capitalize(sensor.status)}
          </p>
        </div>
      ))}
    </div>
  );
}
