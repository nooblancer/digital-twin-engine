export type ComponentStatusValue = 'healthy' | 'degraded' | 'down' | 'unknown';

export interface PipelineHealthResponse {
  overall_status: ComponentStatusValue;
  components: Record<string, ComponentStatusValue>;
  timestamp: string;
}
