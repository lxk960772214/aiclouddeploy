# GPU Cluster Deploy - Configuration Examples

This document provides comprehensive configuration examples for all features in gpu-cluster-deploy.

## Table of Contents

1. [Basic Configuration](#basic-configuration)
2. [Batch Node Configuration](#batch-node-configuration)
3. [Storage Configuration](#storage-configuration)
4. [Network Configuration](#network-configuration)
5. [Modular Execution](#modular-execution)
6. [Jumphost Configuration](#jumphost-configuration)

---

## Basic Configuration

### Minimal Cluster Configuration

```yaml
cluster:
  name: my-gpu-cluster

nodes:
  - hostname: node01
    ip: 192.168.1.1
    roles:
      - gpu_node
      - nfs_client
```

### Complete Node Configuration

```yaml
cluster:
  name: production-cluster

nodes:
  - hostname: gpu-master
    ip: 192.168.1.10
    roles:
      - master
      - nfs_server
      - time_server
    storage:
      type: raid1
      devices:
        - /dev/nvme0n1
        - /dev/nvme1n1
      mount_point: /data
      filesystem: xfs
      format_disk: false
    auth:
      type: key
      username: root
      private_key: /root/.ssh/id_rsa
```

---

## Batch Node Configuration

### Using hosts_file for Batch Node Definition

Define multiple nodes using standard `/etc/hosts` format:

```yaml
cluster:
  name: gpu-cluster

node_batch:
  enabled: true
  hosts_file: hosts.txt  # Path relative to config directory
  roles:
    - gpu_node
  storage_template:
    type: single
    device: /dev/nvme0n1
    mount_point: /ssd
    format_disk: false
  auth_template:
    type: key
    username: admin
    private_key: /home/admin/.ssh/id_rsa
```

**hosts.txt content:**
```
# GPU Compute Nodes
192.168.1.1 gpu-node-01
192.168.1.2 gpu-node-02
192.168.1.3 gpu-node-03
192.168.1.4 gpu-node-04

# Storage Nodes
192.168.2.1 storage-01
192.168.2.2 storage-02
```

### Using hosts_content Directly

Embed hosts content directly in the configuration:

```yaml
cluster:
  name: gpu-cluster

node_batch:
  enabled: true
  hosts_content: |
    192.168.1.1 compute-01
    192.168.1.2 compute-02
    192.168.1.3 compute-03
  roles:
    - gpu_node
```

### Batch Configuration with Node Overrides

Override specific nodes while using batch defaults:

```yaml
cluster:
  name: gpu-cluster

node_batch:
  enabled: true
  hosts_file: hosts.txt
  roles:
    - gpu_node

nodes_override:
  # Override IP address for node02
  - hostname: gpu-node-02
    ip: 10.0.100.2
    roles:
      - gpu_node
      - nfs_server

  # Add a new node not in hosts file
  - hostname: management-node
    ip: 192.168.3.1
    roles:
      - master
      - time_server
```

---

## Storage Configuration

### Single Disk Configuration

```yaml
storage:
  type: single
  device: /dev/nvme0n1
  mount_point: /ssd
  filesystem: ext4
  format_disk: false  # Safety: won't format by default
```

### RAID Configuration

```yaml
storage:
  type: raid1
  devices:
    - /dev/nvme0n1
    - /dev/nvme1n1
  mount_point: /data
  filesystem: xfs
  raid_name: md0
  format_disk: false
```

### LVM Configuration

```yaml
storage:
  type: lvm
  devices:
    - /dev/nvme0n1
    - /dev/nvme1n1
    - /dev/nvme2n1
  mount_point: /storage
  filesystem: xfs
  vg_name: data_vg
  lv_name: data_lv
  lv_size: 100%FREE
  format_disk: false
```

### Storage Template for Batch Nodes

```yaml
node_batch:
  enabled: true
  hosts_file: hosts.txt
  storage_template:
    type: raid1
    devices:
      - /dev/nvme0n1
      - /dev/nvme1n1
    mount_point: /data
    filesystem: xfs
    format_disk: false
```

---

## Network Configuration

### RDMA Device Rename

```yaml
network:
  rdma:
    enabled: true
    rename_pattern: "ib{index}"
    # Only rename specific devices
    devices:
      - mlx5_0
      - mlx5_1
      - mlx5_2
      - mlx5_3
```

### Ethernet Device Rename

```yaml
network:
  ethernet:
    enabled: true
    rename_pattern: "eth{index}"
    devices:
      - ens2f0
      - ens2f1
```

### Non-Continuous Device Mapping

Map devices to non-continuous indices:

```yaml
network:
  rdma:
    enabled: true
    mappings:
      - source: mlx5_0
        target: ib0
      - source: mlx5_2
        target: ib1
      - source: mlx5_4
        target: ib2
      - source: mlx5_6
        target: ib3
```

### Complete Network Configuration

```yaml
network:
  rdma:
    enabled: true
    rename_pattern: "ib{index}"
    devices:
      - mlx5_0
      - mlx5_1
      - mlx5_2
      - mlx5_3
      - mlx5_4
      - mlx5_5
      - mlx5_6
      - mlx5_7

  ethernet:
    enabled: true
    rename_pattern: "eth{index}"
    devices:
      - ens2f0
      - ens2f1

  # Skip certain devices
  skip_devices:
    - mlx5_bond_0
```

---

## Modular Execution

### Execution Plan Structure

Create execution plans in `config/plans/`:

**gpu-only.yaml:**
```yaml
name: gpu-deployment
description: GPU-related deployment steps only
modules:
  - module_id: step_25_nvidia_driver
    name: NVIDIA Driver Installation
    category: gpu
    tags:
      - nvidia
      - driver

  - module_id: step_26_rdma_rename
    name: RDMA Device Rename
    category: network
    tags:
      - rdma
      - infiniband

  - module_id: step_27_cuda
    name: CUDA Toolkit Installation
    category: gpu
    tags:
      - cuda
```

### Execute by Category

Run only network-related steps:

```bash
python -m src.main --config config --categories network
```

### Execute Specific Modules

Run specific modules by ID:

```bash
python -m src.main --config config --modules step_25_nvidia_driver,step_27_cuda
```

### Execute from Plan File

```bash
python -m src.main --config config --plan config/plans/gpu-only.yaml
```

### Available Categories

| Category | Description |
|----------|-------------|
| `system` | System updates, packages |
| `network` | Network configuration, RDMA, Ethernet |
| `storage` | Disk mounting, RAID, LVM |
| `gpu` | GPU drivers, CUDA, NCCL |
| `security` | SSH keys, firewall, authentication |
| `monitoring` | Monitoring tools, logging |

---

## Jumphost Configuration

### Basic Jumphost

```yaml
jumphost:
  enabled: true
  host: jumphost.example.com
  port: 22
  auth:
    type: key
    username: admin
    private_key: /home/admin/.ssh/jumphost_key
```

### Jumphost with Different Node Authentication

```yaml
jumphost:
  enabled: true
  host: jumphost.example.com
  port: 22
  auth:
    type: key
    username: admin
    private_key: /home/admin/.ssh/jumphost_key
  # Separate authentication for cluster nodes
  node_auth:
    type: password
    username: root
    password: ${NODE_PASSWORD}  # Use environment variable
```

### Multi-hop Jumphost

```yaml
jumphost:
  enabled: true
  host: bastion.example.com
  port: 22
  auth:
    type: key
    username: bastion_user
    private_key: /home/user/.ssh/bastion_key
  # Intermediate jump
  intermediate:
    host: internal-jump.example.com
    port: 22
    auth:
      type: key
      username: internal_user
      private_key: /home/user/.ssh/internal_key
```

---

## Complete Example

**config/cluster.yaml:**
```yaml
cluster:
  name: production-gpu-cluster

# Batch node configuration
node_batch:
  enabled: true
  hosts_file: hosts.txt
  roles:
    - gpu_node
  storage_template:
    type: raid1
    devices:
      - /dev/nvme0n1
      - /dev/nvme1n1
    mount_point: /data
    filesystem: xfs
    format_disk: false
  auth_template:
    type: key
    username: root
    private_key: /root/.ssh/id_rsa

# Override specific nodes
nodes_override:
  - hostname: gpu-node-01
    roles:
      - gpu_node
      - master
      - nfs_server

# Network configuration
network:
  rdma:
    enabled: true
    rename_pattern: "ib{index}"
  ethernet:
    enabled: true
    rename_pattern: "eth{index}"

# Jumphost configuration
jumphost:
  enabled: true
  host: bastion.example.com
  port: 22
  auth:
    type: key
    username: admin
    private_key: /home/admin/.ssh/bastion_key
```

**config/hosts.txt:**
```
# Production GPU Cluster
192.168.1.1 gpu-node-01
192.168.1.2 gpu-node-02
192.168.1.3 gpu-node-03
192.168.1.4 gpu-node-04
192.168.1.5 gpu-node-05
192.168.1.6 gpu-node-06
192.168.1.7 gpu-node-07
192.168.1.8 gpu-node-08
```

---

## Environment Variables

Sensitive values can be referenced using environment variables:

```yaml
auth:
  type: password
  username: admin
  password: ${CLUSTER_PASSWORD}
```

Or use a `.env` file:

```bash
# .env
CLUSTER_PASSWORD=your-secure-password
NODE_SSH_KEY=/home/user/.ssh/cluster_key
```

---

## Validation

Before deployment, validate your configuration:

```bash
python -m src.main --config config --validate
```

This will check:
- YAML syntax
- Required fields
- File paths exist
- Network reachability (optional)
