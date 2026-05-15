# Basic Concepts

# Modules (src/{module})

Modules are most important parts of autopilot. They work together to solve problems. A module often contain robust data structures, carefully designed agents and other utility functions.

# Agents (src/{module}/{agent})

Agents are composed of prompts, functions and tool callings, which utilize LLMs to build a pipeline for a project-wise need.

- Agents often have built-in prompts, to increase the performance and stability. These prompts are usually concatenated before the input prompts.

## Agent functions

Agent functions are assist functions for the main function of an agent. They are specific to their belonging agent, which will never be used by other agents.

- The main function of an agent will not be described in the agent functions again.
- These functions are also the **media** when agents receive inputs and output results. Therefore, an agent has at least one exposed function at normal conditions.

# Tools (tools/{tool.py})

Tools obey a standard protocol which has rigorous inputs and outputs, which are designed for solving specific tasks using LLMs. They are public and can be accessed by any agent.

# Utility Functions (utils/{util.py})

Utility functions are just useful functions without using LLMs. They are also public.

- Utility functions are usually designed by AI programming tools.