# GPU集群环境部署参考文档

## 2. 目标

开发一个GPU集群环境部署的程序，集群通常有一个服务器可以从公网ssh登录，可能是密码认证也可能是密钥认证，端口可能修改，然后通过这台服务器可以通过内网ssh到其它服务器。所以先要有一个配置文件进行规划确认，填写登录集群的登录方式，以及集群中需要配置环境的机器ip，用哪台服务器做nfs server。部署时要求能批量执行的操作就批量操作，可以用pdsh批量操作。

## 3. 确认客户要求

| 组件 | 默认版本 | 说明 |
|------|----------|------|
| CUDA | 12.8 | 如果有要求按要求安装 |
| NVIDIA驱动 | 590.48.01 | 如果有要求按要求安装 |
| Kernel | 系统预装版本不变 | 如果有要求按要求安装 |
| MLNX_OFED | MLNX_OFED_LINUX-24.10-2.1.8.0 | 如果有要求按要求安装 |

## 4. 安装依赖的软件包

```bash
sudo apt update -y
sudo apt install build-essential g++ gcc make dkms ntpdate msr-tools traceroute wget sshpass pdsh cpufrequtils sysbench unzip -y
sudo apt -y install build-essential cmake debhelper devscripts fakeroot git libaio-dev libboost-filesystem-dev libboost-program-options-dev libboost-thread-dev libcurl4-openssl-dev libncurses-dev libnuma-dev lintian libssl-dev uuid-dev zlib1g-dev
apt -y install libvulkan1 mesa-vulkan-drivers vulkan-tools
apt-get -y install libglvnd-dev
```

## 5. 检查内核版本，多机调整一致

如果是多机先检查内核版本，确保多机内核版本一致。如果是单机看下没有异常就可以跳过此步骤。

```bash
uname -r
```

确保所有节点均返回一致版本内核。

## 6. 检查glibc版本，多机调整一致

如果是多机确保所有版本glibc版本一致，如果是单机看下没有异常就可以跳过此步骤。

```bash
ldd --version |grep GLIBC
```

确保所有节点版本一致，如果是单节点的话就不用处理。

## 7. 检查openssh版本

需要确保openssh版本没有CVE-2024-6387漏洞

```bash
dpkg -l | grep openssh
```

确保版本高于1:8.9p1-3ubuntu0.10，如果版本低使用以下命令进行更新：

```bash
sudo apt-get update
sudo apt-get install openssh-client -y
```

选择第一个直接回车。

## 8. 设置sudo免密

ubuntu账户操作，root账户这步可以跳过

```bash
echo "ubuntu ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/ubuntu
chmod 440 /etc/sudoers.d/ubuntu
```

## 9. 挂载数据盘

### 9.1. 单盘格式化并挂载

直接格式设备，根据自己的设备名进行修改：

```bash
mkfs.ext4 /dev/nvme0n1p1
```

获取UUID：

```bash
blkid
```

输出示例：
```
/dev/nvme0n1p1: UUID="8929c415-2058-49e2-8030-981c45888183" BLOCK_SIZE="4096" TYPE="ext4" PARTLABEL="primary"
```

最后进行挂载：

```bash
mkdir -p /ssd
cat >>/etc/fstab<<EOF
UUID=8929c415-2058-49e2-8030-981c45888183 /ssd ext4 defaults,nofail 0 0
EOF

mount -a
```

使用命令查看挂载情况：

```bash
df -iTH
```

确保返回挂载点容量、文件系统类型、Inode均符合要求。

### 9.2. 多盘直接使用裸盘做软raid

如果机器上原来有多快磁盘进行过分区，那么我们需要清除分区表信息，做这个操作前需要确认磁盘数据是否可以清除：

```bash
sudo wipefs --all /dev/nvme0n1p1
```

上述操作完成以后我们开始做软raid，两块盘做raid1，三块以上做raid10，以下面四块盘做raid10为例：

```bash
mdadm --create /dev/md0 --level=10 --raid-devices=4 /dev/vdb /dev/vdc /dev/vdd /dev/vde
```

将mdadm信息写入系统文件：

```bash
mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf
```

然后格式化为设备：

```bash
mkfs.ext4 /dev/md0
```

在使用命令查询UUID并进行挂载，操作和单盘一致。

## 10. 设置MSR（5090 + intel 5代 CPU机型需要执行）

设置MSR可以写入到rc.local中来设置开机启动：

```bash
# 设置
wrmsr -a 0xc8b 0xffff

# 查询设置是否正确
rdmsr -a 0xc8b | uniq
```

返回 `cffff` 表示设置成功（没有设置时会返回 `c0fff`）

## 11. rc.local配置方法

设置此文件是为了后面我们方便在系统启动时做一些配置。

```bash
sudo tee /lib/systemd/system/rc-local.service >/dev/null <<EOF
[Unit]
Description=/etc/rc.local Compatibility
Documentation=man:systemd-rc-local-generator(8)
ConditionFileIsExecutable=/etc/rc.local
After=network.target

[Service]
Type=forking
ExecStart=/etc/rc.local start
TimeoutSec=0
RemainAfterExit=yes
GuessMainPID=no

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/rc.local >/dev/null <<EOF
#!/bin/bash

EOF

sudo chmod 755 /etc/rc.local
sudo systemctl daemon-reload
sudo systemctl enable rc-local.service
```

后续需要开机启动的命令可以配置到/etc/rc.local文件中。

## 12. 设置主机名和hosts绑定

主机名和IP写入 /etc/hosts ，同步到所有机器（检查/etc/hosts里是否有 127.0.1.1 主机名 条目，如果有删除后再同步）。

如需要更改主机名：

```bash
hostnamectl set-hostname <主机名>
```

设置hosts绑定：

```bash
sudo tee -a /etc/hosts<<EOF
10.254.43.65 g0271
10.254.42.66 g0272
EOF
```

## 13. 创建ubuntu用户

创建ubuntu用户（uid 1001, gid 1001），CPU节点ubuntu用户到所有GPU节点ubuntu用户ssh免密，ubuntu用户可以免密sudo。

## 14. 设置免密登录和下载登录私钥

### 14.1. 设置节点互相免密登录，多机需操作

首先生成密钥，切换到ubuntu用户再操作生成：

```bash
ssh-keygen -t rsa -N '' -f ~/.ssh/id_rsa
chmod 700 ~/.ssh
cat ~/.ssh/id_rsa.pub >>~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

完成以后下载私钥在本地尝试下是否可以使用私钥登录：

```bash
ssh -i id_rsa ubuntu@IP地址 -p 端口
```

如果有多台机器互相ssh-copy-id一下：

```bash
HOST_LIST="g0271 g0272"

for host in ${HOST_LIST};
do
    if [[ ${host} == $(hostname) ]]; then
        echo "本地不用复制 ssh id !"
    else
        ssh-copy-id $(whoami)@${host}
    fi
done
```

### 14.2. 设置使用私钥登录

```bash
sudo tee -a /etc/ssh/sshd_config<<EOF
ClientAliveInterval 60
ClientAliveCountMax 3
MaxStartups 512
AuthorizedKeysFile .ssh/authorized_keys
EOF
```

编辑 `/etc/ssh/ssh_config`：
```
StrictHostKeyChecking no
```

编辑 `/etc/ssh/sshd_config`：
```
PasswordAuthentication no
ClientAliveInterval 60
ClientAliveCountMax 3
X11Forwarding yes
MaxStartups 512
```

```bash
sudo systemctl restart sshd
```

注意：如果是中卫地域，需要修改 `/etc/ssh/sshd_config.d/50-cloud-init.conf` 中的密码登录配置才会最终生效。

## 15. 设置cpu性能模式

```bash
echo 'GOVERNOR="performance"' | sudo tee /etc/default/cpufrequtils
sudo systemctl restart cpufrequtils
sudo systemctl enable cpufrequtils
sudo cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
```

返回 `performance` 说明设置成功！

```bash
cpufreq-info
```

## 16. 设置文件描述符

```bash
sudo tee /etc/security/limits.conf<<EOF
* soft nofile 1000000
* hard nofile 1000000
* soft nproc 2000000
* hard nproc 2000000
* soft memlock unlimited
* hard memlock unlimited
* soft stack unlimited
* hard stack unlimited
root soft nofile 1000000
root hard nofile 1000000
root soft nproc 2000000
root hard nproc 2000000
root soft memlock unlimited
root hard memlock unlimited
root soft stack unlimited
root hard stack unlimited
EOF
```

设置完成以后需要重启才能生效，后续检查使用如下命令进行检查：

```bash
ulimit -a
```

根据打印的结果核对自己添加的文件描述符是否一致，来确认是否设置成功。

## 17. 禁止系统自动更新

```bash
sudo rm -f /etc/apt/apt.conf.d/50unattended-upgrades
sudo systemctl stop unattended-upgrades.service
sudo systemctl disable unattended-upgrades.service

sudo sed -i '/Update-Package-Lists/s/1/0/' /etc/apt/apt.conf.d/10periodic
sudo sed -i '/Unattended-Upgrade/s/1/0/' /etc/apt/apt.conf.d/10periodic
sudo sed -i '/Update-Package-Lists/s/1/0/' /etc/apt/apt.conf.d/20auto-upgrades
sudo sed -i '/Unattended-Upgrade/s/1/0/' /etc/apt/apt.conf.d/20auto-upgrades

sudo systemctl stop unattended-upgrades.service
sudo systemctl disable unattended-upgrades.service
```

创建 `/etc/apt/preferences.d/nolinuxupgrades`：
```
Package: linux-*
Pin: version *
Pin-Priority: -1
```

锁定内核相关软件：

```bash
for i in `dpkg -l | grep -E '^(ii|hi)\s+linux-(generic|headers|image|modules)' | awk '!/linux-(generic|headers-generic|image-generic)/ {print $2}' | grep 'generic'`;do sudo apt-mark hold $i;done
```

检查内核相关软件是否被hold了：

```bash
sudo apt-mark showhold
```

## 18. 固定内核版本

```bash
kernel_version=$(uname -r)

# 要修改的GRUB配置文件路径
grub_config="/etc/default/grub"

# 检查第6行是否包含 GRUB_DEFAULT=
if grep -q "^GRUB_DEFAULT=" "$grub_config"; then
    # 检查第6行是否是GRUB_DEFAULT=开头
    current_grub_default=$(sed -n '6p' "$grub_config")
    if [[ "$current_grub_default" == GRUB_DEFAULT=* ]]; then
        # 使用sed命令替换第6行的GRUB_DEFAULT值为新的内核版本
        sudo sed -i "6s|^GRUB_DEFAULT=.*|GRUB_DEFAULT=\"Advanced options for Ubuntu>Ubuntu, with Linux $kernel_version\"|" $grub_config
        # 更新 grub 配置
        sudo update-grub
        echo "内核版本已更新到GRUB配置中，当前内核版本：$kernel_version"
    else
        echo "第6行不符合预期格式，未进行修改。"
    fi
else
    echo "没有找到GRUB_DEFAULT配置项，未进行修改。"
fi
```

## 19. 更改时区、更新系统时间

```bash
sudo timedatectl set-timezone Asia/Shanghai
timedatectl
sudo ntpdate -u ntp.aliyun.com
```

## 20. 禁用ipv6

```bash
echo 'net.ipv6.conf.all.disable_ipv6 = 1' | sudo tee -a /etc/sysctl.conf
sysctl -p
```

## 21. 触发vmcore日志

```bash
echo "kernel.hung_task_panic=1" >> /etc/sysctl.conf
echo "kernel.softlockup_panic=1" >> /etc/sysctl.conf
sysctl -p
```

## 22. 禁止系统休眠

```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
sudo systemctl status sleep.target
```

## 23. 安装mellanox驱动

注意：如果在安装MLNX_OFED之前已安装NVIDIA GPU驱动程序，则必须卸载并重新安装GPU驱动程序，以确保nvidia-peermem能够使用MLNX_OFED提供的RDMA API进行编译。

安装包下载地址：https://network.nvidia.com/products/infiniband-drivers/linux/mlnx_ofed/

```bash
sudo ./mlnxofedinstall --add-kernel-support --skip-distro-check --force --enable-opensm
```

安装完成直接重启，使用如下命令进行检查：

```bash
ibstat
```

预期输出：
```
CA 'mlx5_bond_0'
        CA type: MT4119
        Number of ports: 1
        Firmware version: 16.35.4506
        Hardware version: 0
        Node GUID: 0xe8ebd3030030981e
        System image GUID: 0xe8ebd3030030981e
        Port 1:
                State: Active
                Physical state: LinkUp
                Rate: 25
                Base lid: 0
                LMC: 0
                SM lid: 0
                Capability mask: 0x00010000
                Port GUID: 0xeaebd3fffe30981f
                Link layer: Ethernet
```

返回上述说明驱动安装成功，卡状态确保是Active。

使用命令查询网卡模式：

```bash
cma_roce_mode -d mlx5_bond_0
# 返回 RoCE v2 就是RoCE协议
```

## 24. 禁用系统nouveau驱动

```bash
sudo tee -a /etc/modprobe.d/blacklist.conf<<EOF
blacklist nouveau
blacklist lbm‐nouveau
options nouveau modeset=0
alias nouveau off
alias lbm‐nouveau off
EOF

sudo update-initramfs -k $(uname -r) -c
```

做完重启下，然后使用如下命令进行检查：

```bash
lsmod |grep nouveau
```

没有任何返回说明设置成功，接下来就可以安装下GPU卡驱动。

## 25. 安装GPU驱动

驱动下载地址：https://www.nvidia.cn/drivers/lookup/

```bash
apt -y install libvulkan1 mesa-vulkan-drivers vulkan-tools
apt-get -y install libglvnd-dev

export DRIVER_VERSION=570.172.08
chmod +x ./NVIDIA-Linux-x86_64-${DRIVER_VERSION}.run
sudo ./NVIDIA-Linux-x86_64-${DRIVER_VERSION}.run -s --dkms

cp /etc/vulkan/icd.d/nvidia_icd.json /usr/share/vulkan/icd.d/nvidia_icd.json
```

使用命令进行验证：

```bash
nvidia-smi
```

## 26. 安装nvidia-fabricmanager

首先检查是否是nvlink的显卡：

```bash
nvidia-smi nvlink --status
```

如果有返回信息说明是nvlink的卡，需要安装fabricmanager，如果没有则无需安装。

fabricmanager版本需要和驱动一致：

```bash
export DRIVER_VERSION=570.172.08
wget https://developer.download.nvidia.cn/compute/cuda/repos/ubuntu2204/x86_64/nvidia-fabricmanager-$(echo $DRIVER_VERSION | awk -F '.' '{print $1}')_${DRIVER_VERSION}-1_amd64.deb
sudo dpkg -i nvidia-fabricmanager-$(echo $DRIVER_VERSION | awk -F '.' '{print $1}')_${DRIVER_VERSION}-1_amd64.deb

sudo systemctl daemon-reload
sudo systemctl start nvidia-fabricmanager.service
sudo systemctl enable nvidia-fabricmanager.service
sudo systemctl status nvidia-fabricmanager.service
```

## 27. 安装cuda toolkit

CUDA下载地址：https://developer.nvidia.com/cuda-toolkit-archive

```bash
export CUDA_TOOLKIT=cuda_12.8.0_570.86.10_linux.run
chmod +x ${CUDA_TOOLKIT}
sudo ./${CUDA_TOOLKIT} --toolkit --no-drm --silent
CUDA_VERSION=`readlink -f /usr/local/cuda`

echo "export PATH=/usr/local/${CUDA_VERSION}/bin:\$PATH" | sudo tee -a /etc/profile
echo "export LD_LIBRARY_PATH=/usr/local/${CUDA_VERSION}/lib64:\$LD_LIBRARY_PATH" | sudo tee -a /etc/profile
source /etc/profile
nvcc -V
```

## 28. 安装nccl通信库(可选)

nccl依赖于cuda库，所以需要安装完cuda toolkit库再进行nccl的安装。

### 28.1. 编译安装nccl

```bash
COMPUTE_CAP=`nvidia-smi --query-gpu=compute_cap --format=csv | grep -v compute_cap | head -1`
COMPUTE_SM=$(echo "($COMPUTE_CAP * 10)/1" | bc)
git clone https://github.com/NVIDIA/nccl.git
cd nccl
mkdir /home/ubuntu/nccl
make -j$(nproc) src.build BUILDDIR=/home/ubuntu/nccl CUDA_HOME=/usr/local/cuda NVCC_GENCODE="-gencode=arch=compute_${COMPUTE_SM},code=sm_${COMPUTE_SM}"
```

使用时需要注意需要添加这两个环境变量：

```bash
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/home/ubuntu/nccl/lib
export PATH=$PATH:/home/ubuntu/nccl/bin
```

## 29. 检查IB/RoCE的mlx5_x网卡名字一致性

IB/RoCE网卡 mlx5_x设备改名命令：

```bash
# 例如把mlx5_5改成mlx5_6
rdma dev set mlx5_5 mlx5_6
```

如果存在冲突可以先把冲突的网卡重命名为 `tmp_mlx5_?`。

### RDMA设备改名脚本

参考文档中的完整脚本 `/usr/local/bin/rdma-rename.sh`。

### systemd服务

```bash
sudo tee /lib/systemd/system/rdma-rename.service >/dev/null <<EOF
[Unit]
Description=RDMA Device Rename Service
After=network-online.target
Before=gpfs.service
Requires=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/rdma-rename.sh
RemainAfterExit=yes
TimeoutStartSec=300
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable rdma-rename.service
```

### 网络接口udev规则（可选）

创建 `/etc/udev/rules.d/82-persistent-ib-naming.rules`，对照 `ibdev2netdev -v` 输出的pci槽位ID绑定设备和名称。

## 30. 设置GPU持久模式

```bash
sudo tee /etc/systemd/system/nvidia-persistence-mode.service >/dev/null <<EOF
[Unit]
Description=Enable NVIDIA GPU Persistence Mode
After=display-manager.service
Wants=sysinit.target

[Service]
Type=oneshot
ExecStart=/usr/bin/nvidia-smi -pm 1
User=root

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable nvidia-persistence-mode.service
sudo systemctl start nvidia-persistence-mode.service
```

## 31. 内核加载nvidia相关模块

```bash
# nvidia_peermem加入内核模块，不加载不支持gpu direct rdma
echo "nvidia_peermem" | sudo tee /etc/modules-load.d/nvidia.conf

# 开启IBGDA支持，使用deepep时会用到
sudo tee /etc/modprobe.d/nvidia.conf >/dev/null << EOF
options nvidia NVreg_EnableStreamMemOPs=1 NVreg_RegistryDwords="PeerMappingOverride=1;" NVreg_EnableGpuFirmware=0
EOF

sudo update-initramfs -u
```

重启后验证：

```bash
lsmod | grep nvidia_peermem
cat /proc/driver/nvidia/params | grep -E '(EnableStreamMemOPs|RegistryDwords|EnableGpuFirmware):'
```

## 32. 关闭ACS

创建 `/usr/local/bin/disable_acs.sh`：

```bash
#!/bin/bash
#
# Copyright (c) 2018, NVIDIA CORPORATION.  All rights reserved.
#

# must be root to access extended PCI config space
if [ "$EUID" -ne 0 ]; then
  echo "ERROR: $0 must be run as root"
  exit 1
fi

for BDF in `lspci -d "*:*:*" | awk '{print $1}'`; do
    # skip if it doesn't support ACS
    setpci -v -s ${BDF} ECAP_ACS+0x6.w > /dev/null 2>&1
    if [ $? -ne 0 ]; then
            continue
    fi

    logger "Disabling ACS on `lspci -s ${BDF}`"
    setpci -v -s ${BDF} ECAP_ACS+0x6.w=0000
    if [ $? -ne 0 ]; then
        logger "Error disabling ACS on ${BDF}"
            continue
    fi
    NEW_VAL=`setpci -v -s ${BDF} ECAP_ACS+0x6.w | awk '{print $NF}'`
    if [ "${NEW_VAL}" != "0000" ]; then
        logger "Failed to disable ACS on ${BDF}"
            continue
    fi
done
exit 0
```

在 `/etc/rc.local` 中添加：

```bash
bash /usr/local/bin/disable_acs.sh
```

## 33. 内部时间同步服务器，多机需操作

### 33.1. server端操作

```bash
sudo tee /etc/chrony/chrony.conf >/dev/null <<EOF
server 127.127.1.0 iburst
local stratum 10
driftfile /var/lib/chrony/drift
makestep 1.0 3
rtcsync
logdir /var/log/chrony
allow all
EOF

sudo systemctl restart chrony
sudo systemctl enable chrony
sudo chronyc sourcestats -v
```

### 33.2. client端操作

```bash
sudo tee /etc/chrony/chrony.conf >/dev/null <<EOF
server <server端节点的IP> iburst
driftfile /var/lib/chrony/drift
makestep 1.0 3
rtcsync
logdir /var/log/chrony
EOF

sudo systemctl restart chrony
sudo systemctl enable chrony
sudo chronyc sourcestats -v
```

## 34. 配置挂载NFS网络存储(可选)

### server端配置

```bash
sudo apt install -y nfs-kernel-server
sudo mkdir -p /ssd/nfs
sudo chmod -R 777 /ssd/nfs
echo "/ssd/nfs <共享的client端IP或者IP段>(rw,sync,no_subtree_check)" | sudo tee -a /etc/exports
sudo systemctl restart nfs-server
sudo systemctl enable nfs-server
sudo exportfs -arv
```

检查：

```bash
showmount -e <当前server的IP>
```

### client端配置

```bash
sudo apt install -y nfs-common
sudo mkdir -p /data
timeout 10 sudo mount -t nfs -o rw,sync,hard,intr,timeo=5,retrans=3 <server的IP>:/ssd/nfs /data
```

检查：

```bash
df -h
```
