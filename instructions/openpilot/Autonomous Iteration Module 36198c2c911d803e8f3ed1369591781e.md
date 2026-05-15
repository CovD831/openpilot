# Autonomous Iteration Module

This is the core agent of AGI implementation. It contains robust pipelines, which are designed to provide a stable iteration process for any project.

When a user launches a query, the pipeline is as follows:

```python
Run Context Loader;
Run Goal Maker;
for each goal:
	Run Task Designer;
	for each task:
		Run Task Decomposer until the subtask is easy to be solved;
		for each subtask:
			Run Task Executor;
```

# Context Loader

We load all related context, mainly from the memory vault agent, and concatenate them into a prompt, which includes:

- System prompt (fix)
- Compressed dialog history (from memory module)
- Related files (from memory module)
- Related memories (from memory module)
- Virtual environment info (from memory module)

# Goal Maker

It takes the context, and use fixed prompt to generate improvement directions for the project. Examples are:

- improve the UI
- add a new function
- clean the code

# Task Designer

It takes the context and a goal as input, and outputs the specific tasks.

For example, given a Gluttonous Snake game project and a goal ‘add a new function’, the task designer possibly generate a task named ‘add a new game mode timer, where the time decreases faster when the score increases’. 

# Task Decomposer

It takes the context and a task as inputs, and output subtasks that easily to be solved.

## Agent Functions

### Task Difficulty Evaluator

This function evaluates the difficulty of executing a task.

Input: context, task

Output: difficulty

# Task Executor

It takes the context and a subtask as inputs, and execute a subtask.