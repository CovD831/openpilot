"""Generated OpenPilot agent.

This file was produced by Agent Generator. Slot values are configurable at
runtime so private or one-off data does not need to be hardcoded.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


AGENT_SPEC = {
  "name": "generated_agent",
  "task_summary": "帮我调查一下机器学习",
  "slots": [
    {
      "name": "research_topic",
      "kind": "task",
      "description": "调查的主题",
      "value": "机器学习",
      "required": true,
      "revision_notes": []
    },
    {
      "name": "subdomain_focus",
      "kind": "constraint",
      "description": "重点关注的机器学习子领域",
      "value": "深度学习",
      "required": false,
      "revision_notes": [
        "Filled during empty-slot completion."
      ]
    },
    {
      "name": "depth",
      "kind": "constraint",
      "description": "调查深度（入门/进阶/全面）",
      "value": "入门",
      "required": false,
      "revision_notes": [
        "Filled during empty-slot completion."
      ]
    },
    {
      "name": "output_format",
      "kind": "format",
      "description": "输出形式（报告/总结/笔记等）",
      "value": "报告",
      "required": false,
      "revision_notes": [
        "Filled during empty-slot completion."
      ]
    },
    {
      "name": "language_preference",
      "kind": "constraint",
      "description": "资料语言偏好",
      "value": "中文",
      "required": false,
      "revision_notes": []
    },
    {
      "name": "data_source",
      "kind": "data_source",
      "description": "信息来源偏好",
      "value": null,
      "required": false,
      "revision_notes": [
        "User chose to keep this slot empty."
      ]
    }
  ],
  "pipelines": [
    {
      "id": "pipeline_data_collection",
      "name": "Data collection pipeline",
      "purpose": "Collect data required to build the generated agent.",
      "steps": [
        {
          "id": "step_collect_web",
          "name": "Collect data from web search",
          "strategy": "mixed",
          "inputs": [
            "research_topic",
            "subdomain_focus",
            "depth",
            "output_format",
            "language_preference",
            "data_source"
          ],
          "outputs": [
            "artifact_collected_web"
          ],
          "parameters": {
            "selected_tool": "web_searcher",
            "selected_strategy": "StepStrategy.MIXED",
            "tool_input": {
              "query": "机器学习 概述",
              "max_results": 5,
              "max_pages": 3,
              "max_page_chars": 4000,
              "llm_cleanup": true,
              "cleanup_instruction": "Organize the findings for an agent-generation data preview. Keep concrete facts, source-specific notes, and follow-up query suggestions."
            },
            "llm_cleanup": true,
            "llm_cleanup_requested": true,
            "llm_cleanup_executed": true,
            "cleanup_fallback_warning": null,
            "query": "机器学习 概述",
            "result_count": 5,
            "produced_artifact_ids": [
              "artifact_collected_web"
            ]
          },
          "approved": true
        }
      ],
      "artifacts": [
        "artifact_collected_web"
      ],
      "approved": true,
      "task_summary": "帮我调查一下机器学习",
      "slots": [
        {
          "name": "research_topic",
          "kind": "task",
          "description": "调查的主题",
          "value": "机器学习",
          "required": true,
          "revision_notes": []
        },
        {
          "name": "subdomain_focus",
          "kind": "constraint",
          "description": "重点关注的机器学习子领域",
          "value": "深度学习",
          "required": false,
          "revision_notes": [
            "Filled during empty-slot completion."
          ]
        },
        {
          "name": "depth",
          "kind": "constraint",
          "description": "调查深度（入门/进阶/全面）",
          "value": "入门",
          "required": false,
          "revision_notes": [
            "Filled during empty-slot completion."
          ]
        },
        {
          "name": "output_format",
          "kind": "format",
          "description": "输出形式（报告/总结/笔记等）",
          "value": "报告",
          "required": false,
          "revision_notes": [
            "Filled during empty-slot completion."
          ]
        },
        {
          "name": "language_preference",
          "kind": "constraint",
          "description": "资料语言偏好",
          "value": "中文",
          "required": false,
          "revision_notes": []
        },
        {
          "name": "data_source",
          "kind": "data_source",
          "description": "信息来源偏好",
          "value": null,
          "required": false,
          "revision_notes": [
            "User chose to keep this slot empty."
          ]
        }
      ]
    },
    {
      "id": "pipeline_data_processing",
      "name": "Data processing pipeline",
      "purpose": "Transform collected data into reusable agent output behavior.",
      "steps": [
        {
          "id": "step_process_data",
          "name": "Process collected data",
          "strategy": "function",
          "inputs": [
            "artifact_collected_web",
            "research_topic",
            "subdomain_focus",
            "depth",
            "output_format",
            "language_preference",
            "data_source"
          ],
          "outputs": [
            "artifact_processed_result"
          ],
          "parameters": {
            "function": "agent_generator.data_processor.process_data",
            "processing_slots": [],
            "format_slots": [
              {
                "name": "output_format",
                "kind": "format",
                "description": "输出形式（报告/总结/笔记等）",
                "value": "报告",
                "required": false,
                "revision_notes": [
                  "Filled during empty-slot completion."
                ]
              }
            ]
          },
          "approved": true
        }
      ],
      "artifacts": [
        "artifact_processed_result"
      ],
      "approved": true,
      "task_summary": "帮我调查一下机器学习",
      "slots": [
        {
          "name": "research_topic",
          "kind": "task",
          "description": "调查的主题",
          "value": "机器学习",
          "required": true,
          "revision_notes": []
        },
        {
          "name": "subdomain_focus",
          "kind": "constraint",
          "description": "重点关注的机器学习子领域",
          "value": "深度学习",
          "required": false,
          "revision_notes": [
            "Filled during empty-slot completion."
          ]
        },
        {
          "name": "depth",
          "kind": "constraint",
          "description": "调查深度（入门/进阶/全面）",
          "value": "入门",
          "required": false,
          "revision_notes": [
            "Filled during empty-slot completion."
          ]
        },
        {
          "name": "output_format",
          "kind": "format",
          "description": "输出形式（报告/总结/笔记等）",
          "value": "报告",
          "required": false,
          "revision_notes": [
            "Filled during empty-slot completion."
          ]
        },
        {
          "name": "language_preference",
          "kind": "constraint",
          "description": "资料语言偏好",
          "value": "中文",
          "required": false,
          "revision_notes": []
        },
        {
          "name": "data_source",
          "kind": "data_source",
          "description": "信息来源偏好",
          "value": null,
          "required": false,
          "revision_notes": [
            "User chose to keep this slot empty."
          ]
        }
      ]
    }
  ],
  "entry_function": "run",
  "dependencies": [],
  "agent_file": "/Users/yanning/Projects/openpilot/Code/generated_agents/generated_agent.py"
}


def run(**slot_overrides: Any) -> dict[str, Any]:
    """Return a replay-ready agent execution plan with applied slot overrides."""
    spec = deepcopy(AGENT_SPEC)
    slots = spec.get("slots", [])
    for slot in slots:
        name = slot.get("name")
        if name in slot_overrides:
            slot["value"] = slot_overrides[name]

    return {
        "agent": spec.get("name"),
        "task_summary": spec.get("task_summary"),
        "slots": slots,
        "pipelines": spec.get("pipelines", []),
        "entry_function": spec.get("entry_function", "run"),
    }
