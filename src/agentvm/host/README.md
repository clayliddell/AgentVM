## agentvm.host

`agentvm.host` provides host-side scheduling primitives: CPU topology awareness and capacity accounting used by higher-level managers.

### Public API Summary

- `CPUTopology`: immutable topology snapshot.
- `CPUMapManager`: discovers host topology and allocates cpusets.
- `detect_nested_virt_support`: checks nested KVM support.
- `HostCapacity`: immutable capacity snapshot.
- `CapacityCheckResult`: structured resource check result.
- `CapacityManager`: computes host capacity and reconciles tracked allocations.

### LLD Reference

- `docs/designs/HOST-MANAGER-LLD.md`
- `docs/designs/METADATA-STORE-LLD.md`

### Usage Example

```python
from agentvm.config import AgentVMConfig
from agentvm.host import CPUMapManager

config = AgentVMConfig.load()
cpuset, numa_node = CPUMapManager().allocate_cores(
    count=config.resources.default_cpu_cores,
    reserved=config.resources.reserved_cores,
    already_allocated=[],
)
print(cpuset, numa_node)
```
