# TASK: <short title>

## Goal
<One or two sentences. What exactly should be derived or computed.>

## Inputs
- Model / Hamiltonian: <equation or reference, with every symbol defined>
- Parameters: <name = value unit, ...>
- Conventions: <sign of alpha, units for alpha (meV nm), basis ordering, k direction, ...>

## Deliverable
- <e.g. closed-form alpha(R, E_z) and its value at R = 50 nm, E_z = 1 mV/nm, in meV nm>

## Acceptance criteria (written before the run)
- [ ] Limits: <e.g. alpha -> 0 as E_z -> 0>; <e.g. large-R limit equals planar result X>
- [ ] Cross-check: <what independent numerical route must agree, and tolerance>
- [ ] Units: <final quantity must be CONSISTENT with meV*nm>
- [ ] Known value: <reproduce number N from paper/previous run within x %>

## Out of scope
- <things the agent must NOT do, e.g. change the model, add Dresselhaus terms>

## Budget
- Max <N> tool calls / <M> major steps. At the budget, stop and report.

## Instructions
Follow the `symbolic-computation` skill. Write the result to ANSWER.md in this directory.
