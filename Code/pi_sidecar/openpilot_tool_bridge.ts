import net from "node:net";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type BridgeResponse = {
  toolCallId: string;
  success: boolean;
  content: string;
};

const MAX_RESPONSE_BYTES = 65_536;
// Must exceed the longest legitimate tool wait — bash runs up to 60s inside
// the gateway, and an approval gate holds the call until the human answers
// (the old 5s here is what made every tool "time out" while a card was up).
const SOCKET_TIMEOUT_MS = Number(process.env.OPENPILOT_TOOL_TIMEOUT_MS ?? 120_000);

function invokeGateway(payload: Record<string, unknown>, signal?: AbortSignal): Promise<BridgeResponse> {
  const socketPath = process.env.OPENPILOT_PI_TOOL_SOCKET;
  if (!socketPath) throw new Error("OPENPILOT_PI_TOOL_SOCKET is not configured");
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(socketPath);
    let buffer = Buffer.alloc(0);
    const abort = () => socket.destroy(signal?.reason instanceof Error ? signal.reason : new Error("aborted"));
    signal?.addEventListener("abort", abort, { once: true });
    socket.setTimeout(SOCKET_TIMEOUT_MS, () => socket.destroy(new Error("gateway timeout")));
    socket.on("connect", () => socket.write(`${JSON.stringify(payload)}\n`));
    socket.on("data", (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length > MAX_RESPONSE_BYTES) {
        reject(new Error("gateway response exceeds the configured bound"));
        socket.destroy();
        return;
      }
      const newline = buffer.indexOf(0x0a);
      if (newline < 0) return;
      try {
        const response = JSON.parse(buffer.subarray(0, newline).toString("utf8")) as BridgeResponse;
        resolve(response);
        socket.end();
      } catch (error) {
        reject(error);
        socket.destroy();
      }
    });
    socket.on("error", reject);
    socket.on("close", () => signal?.removeEventListener("abort", abort));
  });
}

export default function openpilotToolBridge(pi: ExtensionAPI) {
  pi.registerTool({
    name: "openpilot_read",
    label: "OpenPilot Read",
    description: "Read one project-owned path through the OpenPilot Action Gateway.",
    parameters: Type.Object({
      path: Type.String({ description: "Project-relative file path admitted by OpenPilot" }),
      offset: Type.Optional(Type.Integer({ description: "1-based line to start reading from (default 1)" })),
      limit: Type.Optional(Type.Integer({ description: "Max lines per read (default 400, max 800)" })),
    }),
    executionMode: "sequential",
    async execute(toolCallId, params, signal) {
      const response = await invokeGateway(
        { type: "tool_call", toolName: "openpilot_read", toolCallId, args: params },
        signal,
      );
      if (!response.success) throw new Error(response.content);
      return {
        content: [{ type: "text", text: response.content }],
        details: { gateway: "openpilot", success: response.success },
      };
    },
  });

  pi.registerTool({
    name: "openpilot_patch",
    label: "OpenPilot Patch",
    description: "Apply one scoped replacement through the OpenPilot Action Gateway.",
    parameters: Type.Object({
      path: Type.String({ description: "Project-relative path in the declared write scope" }),
      lineStart: Type.Integer({ minimum: 1 }),
      lineEnd: Type.Integer({ minimum: 1 }),
      replacementText: Type.String(),
    }),
    executionMode: "sequential",
    async execute(toolCallId, params, signal) {
      const response = await invokeGateway(
        { type: "tool_call", toolName: "openpilot_patch", toolCallId, args: params },
        signal,
      );
      if (!response.success) throw new Error(response.content);
      return {
        content: [{ type: "text", text: response.content }],
        details: { gateway: "openpilot", success: response.success },
      };
    },
  });

  pi.registerTool({
    name: "openpilot_write",
    label: "OpenPilot Write",
    description: "Create or overwrite one admitted path through the OpenPilot Action Gateway.",
    parameters: Type.Object({
      path: Type.String({ description: "Project-relative path in the declared write scope" }),
      content: Type.String({ description: "Full file content to write" }),
    }),
    executionMode: "sequential",
    async execute(toolCallId, params, signal) {
      const response = await invokeGateway(
        { type: "tool_call", toolName: "openpilot_write", toolCallId, args: params },
        signal,
      );
      if (!response.success) throw new Error(response.content);
      return {
        content: [{ type: "text", text: response.content }],
        details: { gateway: "openpilot", success: response.success },
      };
    },
  });

  pi.registerTool({
    name: "openpilot_bash",
    label: "OpenPilot Bash",
    description: "Run one command in the project root through the OpenPilot Action Gateway; every command needs an explicit human-approved consent.",
    parameters: Type.Object({
      command: Type.String({ description: "Exact shell command to run in the project root" }),
    }),
    executionMode: "sequential",
    async execute(toolCallId, params, signal) {
      const response = await invokeGateway(
        { type: "tool_call", toolName: "openpilot_bash", toolCallId, args: params },
        signal,
      );
      if (!response.success) throw new Error(response.content);
      return {
        content: [{ type: "text", text: response.content }],
        details: { gateway: "openpilot", success: response.success },
      };
    },
  });

  pi.registerTool({
    name: "openpilot_search",
    label: "OpenPilot Search",
    description: "Search project files for a substring or regex through the OpenPilot Action Gateway.",
    parameters: Type.Object({
      pattern: Type.String({ description: "Substring or regular expression to find" }),
      glob: Type.Optional(Type.String({ description: "Optional glob filter like *.py" })),
    }),
    executionMode: "sequential",
    async execute(toolCallId, params, signal) {
      const response = await invokeGateway(
        { type: "tool_call", toolName: "openpilot_search", toolCallId, args: params },
        signal,
      );
      if (!response.success) throw new Error(response.content);
      return {
        content: [{ type: "text", text: response.content }],
        details: { gateway: "openpilot", success: response.success },
      };
    },
  });

  pi.registerTool({
    name: "openpilot_obs",
    label: "OpenPilot Observation",
    description:
      "Retrieve the full recorded text of one oversized tool output by its observation id. " +
      "Read-only and free — use it whenever a masked observation [observation ... stored] matters again.",
    parameters: Type.Object({
      id: Type.String({ description: "Observation id shown in the [observation ...] placeholder" }),
    }),
    executionMode: "sequential",
    async execute(toolCallId, params, signal) {
      const response = await invokeGateway(
        { type: "tool_call", toolName: "openpilot_obs", toolCallId, args: params },
        signal,
      );
      if (!response.success) throw new Error(response.content);
      return {
        content: [{ type: "text", text: response.content }],
        details: { gateway: "openpilot", success: response.success },
      };
    },
  });

  pi.registerTool({
    name: "openpilot_tasks",
    label: "OpenPilot Parallel Tasks",
    description:
      "Delegate 2-4 independent subtasks to op0 subagents running in parallel, " +
      "each optionally in its own git worktree. Returns one structured report per task.",
    parameters: Type.Object({
      tasks: Type.Array(
        Type.Object({
          task: Type.String({ description: "The complete, self-contained task" }),
          validate: Type.Optional(Type.String({ description: "Command that must exit 0 for done" })),
          worktree: Type.Optional(Type.Boolean({ description: "Isolate file changes in a git worktree" })),
        }),
        { minItems: 2, maxItems: 4 },
      ),
    }),
    executionMode: "sequential",
    async execute(toolCallId, params, signal) {
      const response = await invokeGateway(
        { type: "tool_call", toolName: "openpilot_tasks", toolCallId, args: params },
        signal,
      );
      if (!response.success) throw new Error(response.content);
      return {
        content: [{ type: "text", text: response.content }],
        details: { gateway: "openpilot", success: response.success },
      };
    },
  });

  pi.registerTool({
    name: "openpilot_tasks",
    label: "OpenPilot Parallel Tasks",
    description:
      "Delegate 2-4 independent subtasks to op0 subagents running in parallel, " +
      "each optionally in its own git worktree. Returns one structured report per task.",
    parameters: Type.Object({
      tasks: Type.Array(
        Type.Object({
          task: Type.String({ description: "The complete, self-contained task" }),
          validate: Type.Optional(Type.String({ description: "Command that must exit 0 for done" })),
          worktree: Type.Optional(Type.Boolean({ description: "Isolate file changes in a git worktree" })),
        }),
        { minItems: 2, maxItems: 4 },
      ),
    }),
    executionMode: "sequential",
    async execute(toolCallId, params, signal) {
      const response = await invokeGateway(
        { type: "tool_call", toolName: "openpilot_tasks", toolCallId, args: params },
        signal,
      );
      if (!response.success) throw new Error(response.content);
      return {
        content: [{ type: "text", text: response.content }],
        details: { gateway: "openpilot", success: response.success },
      };
    },
  });

  pi.registerTool({
    name: "openpilot_task",
    label: "OpenPilot Task",
    description:
      "Delegate one self-contained subtask to an op0 subagent with its own context window. " +
      "Use for broad exploration or independent analysis; never for a step you can do directly.",
    parameters: Type.Object({
      task: Type.String({ description: "The complete, self-contained task for the subagent" }),
      validate: Type.String({
        description:
          "Optional shell command that must exit 0 for the task to count as done. " +
          "Its verdict is evidence, not the subagent's own claim.",
      }),
    }),
    executionMode: "sequential",
    async execute(toolCallId, params, signal) {
      const response = await invokeGateway(
        { type: "tool_call", toolName: "openpilot_task", toolCallId, args: params },
        signal,
      );
      if (!response.success) throw new Error(response.content);
      return {
        content: [{ type: "text", text: response.content }],
        details: { gateway: "openpilot", success: response.success },
      };
    },
  });
}
