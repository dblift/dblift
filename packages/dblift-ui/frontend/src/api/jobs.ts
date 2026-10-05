import { ApiError, authHeaders, request, requestText } from "./client";
import type { JobEvent, JobResult } from "./types";

const FINISHED = "job.finished";

/** Incremental parser for the server's `data: <json>` event stream. */
export class SseParser {
  private rest = "";

  push(chunk: string): JobEvent[] {
    this.rest += chunk;
    const events: JobEvent[] = [];
    let end = this.rest.indexOf("\n\n");
    while (end >= 0) {
      const block = this.rest.slice(0, end);
      this.rest = this.rest.slice(end + 2);
      for (const line of block.split("\n")) {
        if (line.startsWith("data: ")) {
          events.push(JSON.parse(line.slice(6)) as JobEvent);
        }
      }
      end = this.rest.indexOf("\n\n");
    }
    return events;
  }
}

/**
 * Start a job and follow it to its end. The stream is read with fetch because
 * EventSource cannot send the token header.
 */
export async function runJob(
  projectId: string,
  command: string,
  environment: string,
  onEvent: (event: JobEvent) => void,
  params: Record<string, unknown> = {},
): Promise<JobResult> {
  const { job_id } = await request<{ job_id: string }>(`/projects/${projectId}/jobs`, {
    method: "POST",
    body: JSON.stringify({ command, environment, params }),
  });
  const response = await fetch(`/api/jobs/${job_id}/events`, { headers: authHeaders() });
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, "could not read job events");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    for (const event of parser.push(decoder.decode(value, { stream: true }))) {
      onEvent(event);
      if (event.event === FINISHED && event.result) {
        return event.result;
      }
    }
  }
  throw new ApiError(0, "job stream ended before the job finished");
}

export const readJobLog = (jobId: string) => requestText(`/jobs/${jobId}/log`);
