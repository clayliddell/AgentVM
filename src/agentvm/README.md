## agentvm

`agentvm` contains the Python runtime primitives for loading AgentVM configuration and host-management services.

### Public API Summary

- `agentvm.config.AgentVMConfig`: typed config object with YAML/env loading and validation.
- `agentvm.config.ConfigError`: config load and validation exception.
- `agentvm.host.CPUMapManager`: host CPU topology and core allocation utility.
- `agentvm.host.CapacityManager`: host capacity tracking and allocation reconciliation.

### LLD Reference

- `docs/designs/CONFIG-LLD.md`
- `docs/designs/HOST-MANAGER-LLD.md`

### Usage Example

```python
from agentvm.config import AgentVMConfig
from agentvm.host import CapacityManager

config = AgentVMConfig.load()
capacity = CapacityManager(config).get_capacity()
print(capacity.available_cpu)
```
