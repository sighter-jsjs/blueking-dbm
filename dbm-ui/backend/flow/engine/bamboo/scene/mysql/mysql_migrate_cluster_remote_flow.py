"""
TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-DB管理系统(BlueKing-BK-DBM) available.
Copyright (C) 2017-2023 THL A29 Limited, a Tencent company. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
You may obtain a copy of the License at https://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
"""

import copy
import logging.config
from dataclasses import asdict
from datetime import datetime
from typing import Dict, Optional

from django.utils import timezone
from django.utils.translation import ugettext as _

from backend.components import DBConfigApi
from backend.components.dbconfig.constants import FormatType, LevelName
from backend.configuration.constants import DBType, MySQLMonitorPauseTime
from backend.constants import IP_PORT_DIVIDER
from backend.db_meta.enums import ClusterType, InstanceInnerRole, InstanceStatus
from backend.db_meta.models import Cluster
from backend.db_package.models import Package
from backend.db_services.mysql.fixpoint_rollback.handlers import FixPointRollbackHandler
from backend.flow.consts import MediumEnum, MysqlVersionToDBBackupForMap
from backend.flow.engine.bamboo.scene.common.builder import Builder, SubBuilder
from backend.flow.engine.bamboo.scene.common.get_file_list import GetFileList
from backend.flow.engine.bamboo.scene.mysql.common.common_sub_flow import (
    build_surrounding_apps_sub_flow,
    install_mysql_in_cluster_sub_flow,
)
from backend.flow.engine.bamboo.scene.mysql.common.get_master_config import get_instance_config
from backend.flow.engine.bamboo.scene.mysql.common.master_and_slave_switch import master_and_slave_switch_v2
from backend.flow.engine.bamboo.scene.mysql.common.mysql_resotre_data_sub_flow import (
    mysql_restore_master_slave_sub_flow,
)
from backend.flow.engine.bamboo.scene.mysql.common.recover_slave_instance import priv_recover_sub_flow
from backend.flow.engine.bamboo.scene.mysql.common.uninstall_instance import uninstall_instance_sub_flow
from backend.flow.engine.bamboo.scene.spider.common.exceptions import TendbGetBackupInfoFailedException
from backend.flow.engine.bamboo.scene.spider.spider_remote_node_migrate import remote_instance_migrate_sub_flow
from backend.flow.plugins.components.collections.common.add_unlock_ticket_type_config import (
    AddUnlockTicketTypeConfigComponent,
)
from backend.flow.plugins.components.collections.common.download_backup_client import DownloadBackupClientComponent
from backend.flow.plugins.components.collections.common.pause import PauseComponent
from backend.flow.plugins.components.collections.common.pause_with_ticket_lock_check import (
    PauseWithTicketLockCheckComponent,
)
from backend.flow.plugins.components.collections.mysql.clear_machine import MySQLClearMachineComponent
from backend.flow.plugins.components.collections.mysql.exec_actuator_script import ExecuteDBActuatorScriptComponent
from backend.flow.plugins.components.collections.mysql.mysql_checksum_ticket import MySQLCheckSumTicketComponent
from backend.flow.plugins.components.collections.mysql.mysql_crond_control import MysqlCrondMonitorControlComponent
from backend.flow.plugins.components.collections.mysql.mysql_db_meta import MySQLDBMetaComponent
from backend.flow.plugins.components.collections.mysql.trans_flies import TransFileComponent
from backend.flow.utils.base.base_dataclass import AddUnLockTicketTypeKwargs, ReleaseUnLockTicketTypeKwargs
from backend.flow.utils.common_act_dataclass import DownloadBackupClientKwargs
from backend.flow.utils.mysql.common.mysql_cluster_info import get_ports, get_version_and_charset
from backend.flow.utils.mysql.mysql_act_dataclass import (
    ClearMachineKwargs,
    CrondMonitorKwargs,
    DBMetaOPKwargs,
    DownloadMediaKwargs,
    ExecActuatorKwargs,
    MysqlCheckSumKwargs,
)
from backend.flow.utils.mysql.mysql_act_playload import MysqlActPayload
from backend.flow.utils.mysql.mysql_context_dataclass import ClusterInfoContext
from backend.flow.utils.mysql.mysql_db_meta import MySQLDBMeta
from backend.ticket.builders.common.constants import MySQLBackupSource
from backend.ticket.constants import TicketType

logger = logging.getLogger("flow")


class MySQLMigrateClusterRemoteFlow(object):
    """
    构建mysql主从成对迁移抽象类
    支持多云区域操作
    """

    def __init__(self, root_id: str, ticket_data: Optional[Dict]):
        """
        @param root_id : 任务流程定义的root_id
        @param ticket_data : 单据传递参数
        """
        self.root_id = root_id
        self.ticket_data = ticket_data
        self.data = {}

        # 定义备份文件存放到目标机器目录位置
        self.backup_target_path = f"/data/dbbak/{self.root_id}"
        self.local_backup = False
        if self.ticket_data.get("backup_source") == MySQLBackupSource.LOCAL:
            self.local_backup = True

    def migrate_cluster_flow(self, use_for_upgrade=False):
        """
        成对迁移集群主从节点。
        元数据信息修改顺序：
        1 mysql_migrate_cluster_add_instance
        2 mysql_migrate_cluster_add_tuple
        3 mysql_migrate_cluster_switch_storage
        """
        # 构建流程
        cluster_ids = []
        for i in self.ticket_data["infos"]:
            cluster_ids.extend(i["cluster_ids"])

        tendb_migrate_pipeline_all = Builder(
            root_id=self.root_id,
            data=copy.deepcopy(self.ticket_data),
            need_random_pass_cluster_ids=list(set(cluster_ids)),
        )

        # 按照传入的infos信息，循环拼接子流程
        tendb_migrate_pipeline_list = []
        for info in self.ticket_data["infos"]:
            self.data = copy.deepcopy(info)
            cluster_class = Cluster.objects.get(id=self.data["cluster_ids"][0])
            # 确定要迁移的主节点，从节点.
            master_model = cluster_class.storageinstance_set.get(instance_inner_role=InstanceInnerRole.MASTER.value)
            slave = cluster_class.storageinstance_set.filter(
                instance_inner_role=InstanceInnerRole.SLAVE.value, is_stand_by=True
            ).first()
            install_pkg_version = cluster_class.major_version

            # 如果是升级用途的话,需要改变module id
            db_module_id = cluster_class.db_module_id
            self.data["package"] = Package.get_latest_package(
                version=install_pkg_version, pkg_type=MediumEnum.MySQL, db_type=DBType.MySQL
            ).name

            pkg_id = 0
            if use_for_upgrade:
                db_module_id = info["new_db_module_id"]
                pkg_id = info["pkg_id"]
                self.data["package"] = Package.objects.get(id=pkg_id, pkg_type=MediumEnum.MySQL, db_type=DBType.MySQL)

            charset, db_version = get_version_and_charset(
                bk_biz_id=cluster_class.bk_biz_id,
                db_module_id=db_module_id,
                cluster_type=cluster_class.cluster_type,
            )
            self.data["need_checksum"] = self.ticket_data.get("need_checksum", False)
            self.data["master_ip"] = master_model.machine.ip
            self.data["cluster_type"] = cluster_class.cluster_type
            self.data["old_slave_ip"] = slave.machine.ip
            self.data["slave_ip"] = slave.machine.ip
            self.data["mysql_port"] = master_model.port
            self.data["bk_biz_id"] = cluster_class.bk_biz_id
            self.data["bk_cloud_id"] = cluster_class.bk_cloud_id
            self.data["db_module_id"] = db_module_id
            self.data["time_zone"] = cluster_class.time_zone
            self.data["created_by"] = self.ticket_data["created_by"]
            self.data["module"] = db_module_id
            self.data["ticket_type"] = self.ticket_data["ticket_type"]
            self.data["uid"] = self.ticket_data["uid"]
            self.data["ports"] = get_ports(info["cluster_ids"])
            self.data["force"] = info.get("force", False)
            self.data["charset"] = charset
            self.data["db_version"] = db_version
            bk_host_ids = []
            if "bk_new_slave" in self.data.keys():
                bk_host_ids.append(self.data["bk_new_slave"]["bk_host_id"])
            if "bk_new_master" in self.data.keys():
                bk_host_ids.append(self.data["bk_new_master"]["bk_host_id"])

            tendb_migrate_pipeline = SubBuilder(root_id=self.root_id, data=copy.deepcopy(self.data))

            # 解除对proxy替换的单据互斥锁，这个阶段到下一个暂停节点，允许proxy替换单据进入执行
            tendb_migrate_pipeline.add_act(
                act_name=_("解锁部分单据互斥锁"),
                act_component_code=AddUnlockTicketTypeConfigComponent.code,
                kwargs=asdict(
                    AddUnLockTicketTypeKwargs(
                        cluster_ids=self.data["cluster_ids"], unlock_ticket_type_list=[TicketType.MYSQL_PROXY_SWITCH]
                    )
                ),
            )

            # 整机安装数据库
            master = cluster_class.storageinstance_set.get(instance_inner_role=InstanceInnerRole.MASTER.value)
            # db_config example {3306:{"key":val},3307:{"key":val}}
            db_config = get_instance_config(cluster_class.bk_cloud_id, master.machine.ip, self.data["ports"])
            install_sub_pipeline_list = []
            install_sub_pipeline = SubBuilder(root_id=self.root_id, data=copy.deepcopy(self.data))
            install_sub_pipeline.add_sub_pipeline(
                sub_flow=install_mysql_in_cluster_sub_flow(
                    uid=self.data["uid"],
                    root_id=self.root_id,
                    cluster=cluster_class,
                    new_mysql_list=[self.data["new_slave_ip"], self.data["new_master_ip"]],
                    install_ports=self.data["ports"],
                    bk_host_ids=bk_host_ids,
                    pkg_id=pkg_id,
                    db_module_id=str(db_module_id),
                    db_config=db_config,
                )
            )

            #  写入元数据
            cluster = {
                "cluster_ports": self.data["ports"],
                "new_master_ip": self.data["new_master_ip"],
                "new_slave_ip": self.data["new_slave_ip"],
                "bk_cloud_id": cluster_class.bk_cloud_id,
            }
            install_sub_pipeline.add_act(
                act_name=_("安装完毕,写入初始化实例的db_meta元信息"),
                act_component_code=MySQLDBMetaComponent.code,
                kwargs=asdict(
                    DBMetaOPKwargs(
                        db_meta_class_func=MySQLDBMeta.migrate_cluster_add_instance.__name__,
                        cluster=copy.deepcopy(cluster),
                        is_update_trans_data=True,
                    )
                ),
            )
            install_sub_pipeline.add_act(
                act_name=_("安装backup-client工具"),
                act_component_code=DownloadBackupClientComponent.code,
                kwargs=asdict(
                    DownloadBackupClientKwargs(
                        bk_cloud_id=cluster_class.bk_cloud_id,
                        bk_biz_id=int(cluster_class.bk_biz_id),
                        download_host_list=[cluster["new_master_ip"], cluster["new_slave_ip"]],
                    )
                ),
            )

            exec_act_kwargs = ExecActuatorKwargs(
                cluster=cluster,
                bk_cloud_id=cluster_class.bk_cloud_id,
                cluster_type=cluster_class.cluster_type,
                get_mysql_payload_func=MysqlActPayload.get_install_tmp_db_backup_payload.__name__,
            )
            exec_act_kwargs.exec_ip = [cluster["new_master_ip"], cluster["new_slave_ip"]]
            install_sub_pipeline.add_act(
                act_name=_("安装临时备份程序"),
                act_component_code=ExecuteDBActuatorScriptComponent.code,
                kwargs=asdict(exec_act_kwargs),
            )
            install_sub_pipeline_list.append(install_sub_pipeline.build_sub_process(sub_name=_("安装实例")))

            # 生成checksum信息
            checksum_info = {
                "bk_biz_id": cluster_class.bk_biz_id,
                "ticket_type": TicketType.MYSQL_CHECKSUM,
                "remark": _("mysql成对迁移生成checksum单据"),
                "details": {
                    "data_repair": {
                        "is_repair": True,
                        "mode": "manual",
                    },
                    "is_sync_non_innodb": True,
                    "runtime_hour": 48,
                    "infos": [],
                },
            }
            sync_data_sub_pipeline_list = []
            for cluster_id in self.data["cluster_ids"]:
                cluster_model = Cluster.objects.get(id=cluster_id)
                master_model = cluster_model.storageinstance_set.get(
                    instance_inner_role=InstanceInnerRole.MASTER.value
                )
                cluster["new_master_ip"] = self.data["new_master_ip"]
                cluster["new_slave_ip"] = self.data["new_slave_ip"]
                cluster["new_master_port"] = master_model.port
                cluster["new_slave_port"] = master_model.port
                cluster["master_ip"] = self.data["master_ip"]
                cluster["slave_ip"] = self.data["slave_ip"]
                cluster["master_port"] = master_model.port
                cluster["slave_port"] = master_model.port
                cluster["mysql_port"] = master_model.port
                cluster["file_target_path"] = f"/data/dbbak/{self.root_id}/{master_model.port}"
                cluster["cluster_id"] = cluster_model.id
                cluster["bk_cloud_id"] = cluster_model.bk_cloud_id
                cluster["change_master_force"] = False
                cluster["change_master"] = False
                cluster["charset"] = self.data["charset"]
                checksum_info["details"]["infos"] = []
                checksum_info["details"]["infos"].append(
                    {
                        "cluster_id": cluster_model.id,
                        "master": {
                            "bk_biz_id": master_model.bk_biz_id,
                            "bk_cloud_id": cluster_model.bk_cloud_id,
                            "bk_host_id": master_model.machine_id,
                            "ip": master_model.machine.ip,
                            "port": master_model.port,
                            "instance_inner_role": InstanceInnerRole.MASTER,
                        },
                        "slaves": [
                            {
                                "bk_biz_id": cluster_model.bk_biz_id,
                                "bk_cloud_id": cluster_model.bk_cloud_id,
                                "ip": self.data["new_master_ip"],
                                "bk_host_id": self.data["bk_new_master"]["bk_host_id"],
                                "port": master_model.port,
                                "instance_inner_role": InstanceInnerRole.REPEATER,
                            },
                        ],
                        "db_patterns": ["*"],
                        "ignore_dbs": [],
                        "table_patterns": ["*"],
                        "ignore_tables": [],
                    }
                )

                sync_data_sub_pipeline = SubBuilder(root_id=self.root_id, data=copy.deepcopy(self.data))
                if self.local_backup:
                    stand_by_slaves = cluster_model.storageinstance_set.filter(
                        instance_inner_role=InstanceInnerRole.SLAVE.value,
                        is_stand_by=True,
                        status=InstanceStatus.RUNNING.value,
                    ).exclude(machine__ip__in=[self.data["new_slave_ip"], self.data["new_master_ip"]])
                    #     从standby从库找备份
                    inst_list = ["{}{}{}".format(master_model.machine.ip, IP_PORT_DIVIDER, master_model.port)]
                    if len(stand_by_slaves) > 0:
                        inst_list.append(
                            "{}{}{}".format(stand_by_slaves[0].machine.ip, IP_PORT_DIVIDER, stand_by_slaves[0].port)
                        )
                    sync_data_sub_pipeline.add_sub_pipeline(
                        sub_flow=mysql_restore_master_slave_sub_flow(
                            root_id=self.root_id,
                            ticket_data=copy.deepcopy(self.data),
                            cluster=cluster,
                            cluster_model=cluster_model,
                            ins_list=inst_list,
                        )
                    )
                else:
                    rollback_time = datetime.now(timezone.utc)
                    rollback_handler = FixPointRollbackHandler(cluster_id=cluster_model.id, check_full_backup=True)
                    backup_info = rollback_handler.query_latest_backup_log(rollback_time)
                    if backup_info is None:
                        logger.error("cluster {} backup info not exists".format(cluster_model.id))
                        raise TendbGetBackupInfoFailedException(message=_("获取集群 {} 的备份信息失败".format(cluster_id)))
                    cluster["backupinfo"] = backup_info
                    sync_data_sub_pipeline.add_sub_pipeline(
                        sub_flow=remote_instance_migrate_sub_flow(
                            root_id=self.root_id, ticket_data=copy.deepcopy(self.data), cluster_info=cluster
                        )
                    )
                    priv_sub_flow = priv_recover_sub_flow(
                        root_id=self.root_id,
                        ticket_data=copy.deepcopy(self.data),
                        cluster_info=cluster,
                        ips=[self.data["new_master_ip"], self.data["new_slave_ip"]],
                    )
                    if priv_sub_flow:
                        sync_data_sub_pipeline.add_sub_pipeline(sub_flow=priv_sub_flow)

                sync_data_sub_pipeline.add_act(
                    act_name=_("数据恢复完毕,写入新主节点和旧主节点的关系链元数据"),
                    act_component_code=MySQLDBMetaComponent.code,
                    kwargs=asdict(
                        DBMetaOPKwargs(
                            db_meta_class_func=MySQLDBMeta.migrate_cluster_add_tuple.__name__,
                            cluster=copy.deepcopy(cluster),
                            is_update_trans_data=True,
                        )
                    ),
                )

                if self.data["need_checksum"]:
                    sync_data_sub_pipeline.add_act(
                        act_name=_("生成checksum单据"),
                        act_component_code=MySQLCheckSumTicketComponent.code,
                        kwargs=asdict(
                            MysqlCheckSumKwargs(
                                bk_biz_id=cluster_model.bk_biz_id,
                                created_by=self.data["created_by"],
                                checksum_info=copy.deepcopy(checksum_info),
                            )
                        ),
                    )
                sync_data_sub_pipeline_list.append(
                    sync_data_sub_pipeline.build_sub_process(sub_name=_("{} 集群恢复数据".format(cluster_model.name)))
                )

            switch_sub_pipeline_list = []
            for cluster_id in self.data["cluster_ids"]:
                switch_sub_pipeline = SubBuilder(root_id=self.root_id, data=copy.deepcopy(self.data))
                cluster_model = Cluster.objects.get(id=cluster_id)
                master_model = cluster_model.storageinstance_set.get(
                    instance_inner_role=InstanceInnerRole.MASTER.value
                )
                other_slave_storage = cluster_model.storageinstance_set.filter(
                    instance_inner_role=InstanceInnerRole.SLAVE.value
                ).exclude(
                    machine__ip__in=[self.data["old_slave_ip"], self.data["new_slave_ip"], self.data["new_master_ip"]]
                )
                other_slaves = [y.machine.ip for y in other_slave_storage]
                cluster = {
                    "cluster_id": cluster_model.id,
                    "bk_cloud_id": cluster_model.bk_cloud_id,
                    "old_master_ip": self.data["master_ip"],
                    "old_master_port": master_model.port,
                    "old_slave_ip": self.data["old_slave_ip"],
                    "old_slave_port": master_model.port,
                    "new_master_ip": self.data["new_master_ip"],
                    "new_master_port": master_model.port,
                    "new_slave_ip": self.data["new_slave_ip"],
                    "new_slave_port": master_model.port,
                    "mysql_port": master_model.port,
                    "master_port": master_model.port,
                    "other_slave_info": other_slaves,
                }
                switch_sub_pipeline.add_sub_pipeline(
                    sub_flow=master_and_slave_switch_v2(
                        root_id=self.root_id,
                        ticket_data=copy.deepcopy(self.data),
                        cluster=cluster_model,
                        cluster_info=copy.deepcopy(cluster),
                    )
                )
                switch_sub_pipeline.add_act(
                    act_name=_("集群切换完成,写入 {} 的元信息".format(cluster_model.name)),
                    act_component_code=MySQLDBMetaComponent.code,
                    kwargs=asdict(
                        DBMetaOPKwargs(
                            db_meta_class_func=MySQLDBMeta.mysql_migrate_cluster_switch_storage.__name__,
                            cluster=cluster,
                            is_update_trans_data=True,
                        )
                    ),
                )
                switch_sub_pipeline.add_act(
                    act_name=_("切换后屏蔽旧实例备份 {} {}").format(self.data["master_ip"], self.data["old_slave_ip"]),
                    act_component_code=MysqlCrondMonitorControlComponent.code,
                    kwargs=asdict(
                        CrondMonitorKwargs(
                            bk_cloud_id=cluster_class.bk_cloud_id,
                            exec_ips=[self.data["master_ip"], self.data["old_slave_ip"]],
                            name="dbbackup",
                            port=master_model.port,
                        )
                    ),
                )
                switch_sub_pipeline_list.append(
                    switch_sub_pipeline.build_sub_process(sub_name=_("集群 {} 切换".format(cluster_model.name)))
                )
            # 第四步 卸载实例
            uninstall_svr_sub_pipeline_list = []
            uninstall_surrounding_sub_pipeline_list = []
            for ip in [self.data["slave_ip"], self.data["master_ip"]]:
                uninstall_surrounding_sub_pipeline = SubBuilder(root_id=self.root_id, data=copy.deepcopy(self.data))
                uninstall_svr_sub_pipeline = SubBuilder(root_id=self.root_id, data=copy.deepcopy(self.data))
                # 考虑到部分实例成对迁移的情况(即拆分)
                cluster = {
                    "uninstall_ip": ip,
                    "remote_port": self.data["ports"],
                    "backend_port": self.data["ports"],
                    "bk_cloud_id": cluster_class.bk_cloud_id,
                }

                uninstall_surrounding_sub_pipeline.add_act(
                    act_name=_("下发db-actor到节点{}".format(ip)),
                    act_component_code=TransFileComponent.code,
                    kwargs=asdict(
                        DownloadMediaKwargs(
                            bk_cloud_id=cluster_class.bk_cloud_id,
                            exec_ip=[ip],
                            file_list=GetFileList(db_type=DBType.MySQL).get_db_actuator_package(),
                        )
                    ),
                )

                uninstall_surrounding_sub_pipeline.add_act(
                    act_name=_("清理实例级别周边配置"),
                    act_component_code=ExecuteDBActuatorScriptComponent.code,
                    kwargs=asdict(
                        ExecActuatorKwargs(
                            exec_ip=ip,
                            cluster_type=ClusterType.TenDBHA,
                            bk_cloud_id=cluster_class.bk_cloud_id,
                            cluster=cluster,
                            get_mysql_payload_func=MysqlActPayload.get_clear_surrounding_config_payload.__name__,
                        )
                    ),
                )

                cluster = {
                    "uninstall_ip": ip,
                    "ports": self.data["ports"],
                    "bk_cloud_id": cluster_class.bk_cloud_id,
                    "cluster_type": cluster_class.cluster_type,
                }
                uninstall_svr_sub_pipeline.add_act(
                    act_name=_("实例卸载前删除元数据"),
                    act_component_code=MySQLDBMetaComponent.code,
                    kwargs=asdict(
                        DBMetaOPKwargs(
                            db_meta_class_func=MySQLDBMeta.uninstall_instance.__name__,
                            is_update_trans_data=True,
                            cluster=cluster,
                        )
                    ),
                )

                uninstall_svr_sub_pipeline.add_act(
                    act_name=_("清理机器配置"),
                    act_component_code=MySQLClearMachineComponent.code,
                    kwargs=asdict(
                        ClearMachineKwargs(
                            exec_ip=ip,
                            bk_cloud_id=cluster_class.bk_cloud_id,
                        )
                    ),
                )
                uninstall_svr_sub_pipeline.add_sub_pipeline(
                    sub_flow=uninstall_instance_sub_flow(
                        root_id=self.root_id, ticket_data=copy.deepcopy(self.data), ip=ip, ports=self.data["ports"]
                    )
                )

                uninstall_surrounding_sub_pipeline_list.append(
                    uninstall_surrounding_sub_pipeline.build_sub_process(sub_name=_("卸载remote节点周边{}".format(ip)))
                )
                uninstall_svr_sub_pipeline_list.append(
                    uninstall_svr_sub_pipeline.build_sub_process(sub_name=_("卸载remote节点{}".format(ip)))
                )
            # 安装实例
            tendb_migrate_pipeline.add_parallel_sub_pipeline(sub_flow_list=install_sub_pipeline_list)
            # 同步配置
            # tendb_migrate_pipeline.add_parallel_sub_pipeline(sub_flow_list=sync_mycnf_sub_pipeline_list)
            # 数据同步
            tendb_migrate_pipeline.add_parallel_sub_pipeline(sub_flow_list=sync_data_sub_pipeline_list)
            #  新机器安装周边组件
            tendb_migrate_pipeline.add_sub_pipeline(
                sub_flow=build_surrounding_apps_sub_flow(
                    bk_cloud_id=cluster_class.bk_cloud_id,
                    master_ip_list=None,
                    slave_ip_list=[self.data["new_slave_ip"], self.data["new_master_ip"]],
                    root_id=self.root_id,
                    parent_global_data=copy.deepcopy(self.data),
                    collect_sysinfo=True,
                    is_install_backup=False,
                    cluster_type=ClusterType.TenDBHA.value,
                    db_backup_pkg_type=MysqlVersionToDBBackupForMap[self.data["db_version"]],
                )
            )
            tendb_migrate_pipeline.add_act(
                act_name=_("屏蔽监控 {} {}").format(self.data["new_master_ip"], self.data["new_slave_ip"]),
                act_component_code=MysqlCrondMonitorControlComponent.code,
                kwargs=asdict(
                    CrondMonitorKwargs(
                        bk_cloud_id=cluster_class.bk_cloud_id,
                        exec_ips=[self.data["new_master_ip"], self.data["new_slave_ip"]],
                        port=0,
                        minutes=MySQLMonitorPauseTime.SLAVE_DELAY,
                    )
                ),
            )

            # 人工确认切换迁移实例, 释放解除之前的prox替换单据互斥
            tendb_migrate_pipeline.add_act(
                act_name=_("人工确认切换,判断互斥单据"),
                act_component_code=PauseWithTicketLockCheckComponent.code,
                kwargs=asdict(
                    ReleaseUnLockTicketTypeKwargs(
                        cluster_ids=self.data["cluster_ids"],
                        release_unlock_ticket_type_list=[TicketType.MYSQL_PROXY_SWITCH],
                    )
                ),
            )
            # 切换迁移实例
            tendb_migrate_pipeline.add_parallel_sub_pipeline(sub_flow_list=switch_sub_pipeline_list)
            tendb_migrate_pipeline.add_sub_pipeline(
                sub_flow=build_surrounding_apps_sub_flow(
                    bk_cloud_id=cluster_class.bk_cloud_id,
                    master_ip_list=[self.data["new_master_ip"]],
                    slave_ip_list=[self.data["new_slave_ip"]],
                    root_id=self.root_id,
                    parent_global_data=copy.deepcopy(self.data),
                    is_init=True,
                    collect_sysinfo=True,
                    cluster_type=ClusterType.TenDBHA.value,
                    db_backup_pkg_type=MysqlVersionToDBBackupForMap[self.data["db_version"]],
                )
            )
            tendb_migrate_pipeline.add_act(
                act_name=_("解除屏蔽监控 {} {}").format(self.data["new_master_ip"], self.data["new_slave_ip"]),
                act_component_code=MysqlCrondMonitorControlComponent.code,
                kwargs=asdict(
                    CrondMonitorKwargs(
                        bk_cloud_id=cluster_class.bk_cloud_id,
                        exec_ips=[self.data["new_master_ip"], self.data["new_slave_ip"]],
                        port=0,
                        enable=True,
                    )
                ),
            )

            if use_for_upgrade:
                data = DBConfigApi.query_conf_item(
                    {
                        "bk_biz_id": str(self.data["bk_biz_id"]),
                        "level_name": LevelName.MODULE,
                        "level_value": str(db_module_id),
                        "conf_file": "deploy_info",
                        "conf_type": "deploy",
                        "namespace": ClusterType.TenDBHA.value,
                        "format": FormatType.MAP,
                    }
                )["content"]
                major_version = data["db_version"]
                tendb_migrate_pipeline.add_act(
                    act_name=_("更新集群db模块"),
                    act_component_code=MySQLDBMetaComponent.code,
                    kwargs=asdict(
                        DBMetaOPKwargs(
                            db_meta_class_func=MySQLDBMeta.update_cluster_module.__name__,
                            cluster={
                                "cluster_ids": self.data["cluster_ids"],
                                "new_module_id": info["new_db_module_id"],
                                "major_version": major_version,
                            },
                        )
                    ),
                )
            tendb_migrate_pipeline.add_parallel_sub_pipeline(sub_flow_list=uninstall_surrounding_sub_pipeline_list)

            # 解除对proxy替换的单据互斥锁，最后卸载旧实例阶段，能允许proxy替换单据进入执行
            tendb_migrate_pipeline.add_act(
                act_name=_("解锁部分单据互斥锁"),
                act_component_code=AddUnlockTicketTypeConfigComponent.code,
                kwargs=asdict(
                    AddUnLockTicketTypeKwargs(
                        cluster_ids=self.data["cluster_ids"], unlock_ticket_type_list=[TicketType.MYSQL_PROXY_SWITCH]
                    )
                ),
            )

            # 卸载流程人工确认
            tendb_migrate_pipeline.add_act(act_name=_("人工确认卸载实例"), act_component_code=PauseComponent.code, kwargs={})
            # 卸载remote节点
            tendb_migrate_pipeline.add_parallel_sub_pipeline(sub_flow_list=uninstall_svr_sub_pipeline_list)
            tendb_migrate_pipeline_list.append(
                tendb_migrate_pipeline.build_sub_process(
                    sub_name=_("{} > {} 成对迁移".format(self.data["master_ip"], self.data["new_master_ip"]))
                )
            )
        # 运行流程
        tendb_migrate_pipeline_all.add_parallel_sub_pipeline(tendb_migrate_pipeline_list)
        tendb_migrate_pipeline_all.run_pipeline(
            init_trans_data_class=ClusterInfoContext(),
            is_drop_random_user=True,
        )
