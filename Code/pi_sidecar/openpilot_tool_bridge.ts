import net from "node:net";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type BridgeResponse = {
  toolCallId: string;
  success: boolean;
  content: string;
};

const MAX_RESPONSE_BYTES = 65_536;
const SOCKET_TIMEOUT_MS = 5_000;

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
}
