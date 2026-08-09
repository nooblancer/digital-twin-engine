'use client';

import { useCallback } from 'react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { DATA_SOURCES } from '@/lib/data-sources';
import { useStore } from '@/store';
import type { DataSourceId } from '@/types';

interface DataSourceSwitcherProps {
  /** Backend endpoint to POST source switch requests to */
  endpoint?: string;
}

export function DataSourceSwitcher({
  endpoint = 'http://localhost:8000/source',
}: DataSourceSwitcherProps) {
  const activeSource = useStore((state) => state.activeSource);
  const isSwitchingSource = useStore((state) => state.ui.isSwitchingSource);
  const setActiveSource = useStore((state) => state.setActiveSource);
  const setSwitchingSource = useStore((state) => state.setSwitchingSource);
  const setError = useStore((state) => state.setError);

  const handleSourceChange = useCallback(
    async (value: string) => {
      const sourceId = value as DataSourceId;

      setSwitchingSource(true);
      setError(null);

      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source: sourceId }),
        });

        if (!response.ok) {
          throw new Error(
            `Failed to switch data source: ${response.status} ${response.statusText}`
          );
        }

        setActiveSource(sourceId);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : 'Failed to switch data source';
        setError(message);
      } finally {
        setSwitchingSource(false);
      }
    },
    [endpoint, setActiveSource, setSwitchingSource, setError]
  );

  return (
    <div className="flex items-center gap-3">
      <label
        htmlFor="data-source-select"
        className="text-sm font-medium text-muted-foreground whitespace-nowrap"
      >
        Data Source
      </label>
      <Select
        value={activeSource}
        onValueChange={handleSourceChange}
        disabled={isSwitchingSource}
      >
        <SelectTrigger id="data-source-select" className="w-[220px]">
          {isSwitchingSource ? (
            <span className="text-muted-foreground">Switching...</span>
          ) : (
            <SelectValue placeholder="Select a data source" />
          )}
        </SelectTrigger>
        <SelectContent>
          {DATA_SOURCES.map((source) => (
            <SelectItem key={source.id} value={source.id}>
              {source.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
