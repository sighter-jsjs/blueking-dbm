# -*- coding: utf-8 -*-
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
from dataclasses import asdict

from django.utils.translation import ugettext as _

from backend.configuration.constants import MYSQL_DATA_RESTORE_TIME, MYSQL_USUAL_JOB_TIME
from backend.db_meta.enums import ClusterType
from backend.flow.consts import MySQLBackupTypeEnum, MysqlChangeMasterType, RollbackType
from backend.flow.engine.bamboo.scene.common.builder import SubBuilder
from backend.flow.engine.bamboo.scene.mysql.common.get_binlog_backup import get_backup_binlog
from backend.flow.engine.bamboo.scene.spider.common.exceptions import TendbGetBinlogFailedException
from backend.flow.plugins.components.collections.mysql.exec_actuator_script import ExecuteDBActuatorScriptComponent
from backend.flow.plugins.components.collections.mysql.mysql_download_backupfile import (
    MySQLDownloadBackupfileComponent,
)
from backend.flow.plugins.components.collections.mysql.mysql_rds_execute import MySQLExecuteRdsComponent
from backend.flow.utils.mysql.mysql_act_dataclass import DownloadBackupFileKwargs, ExecActuatorKwargs, ExecuteRdsKwargs
from backend.flow.utils.mysql.mysql_act_playload import MysqlActPayload
from backend.utils.time import str2datetime


def spider_recover_sub_flow(root_id: str, ticket_data: dict, cluster: dict):
    """
    spider 恢复表结构
    从指定spider列表获取备份介质恢复至指定的spider
    1 获取介质>判断介质来源>恢复数据
    @param root_id: flow流程root_id
    @param ticket_data: 单据 data
    @param cluster: 关联的cluster对象
    """
    sub_pipeline = SubBuilder(root_id=root_id, data=ticket_data)
    exec_act_kwargs = ExecActuatorKwargs(
        bk_cloud_id=int(cluster["bk_cloud_id"]), cluster_type=ClusterType.TenDBCluster, cluster=cluster
    )
    exec_act_kwargs.get_mysql_payload_func = MysqlActPayload.mysql_mkdir_dir.__name__
    exec_act_kwargs.exec_ip = cluster["rollback_ip"]
    sub_pipeline.add_act(
        act_name=_("创建目录 {}".format(cluster["file_target_path"])),
        act_component_code=ExecuteDBActuatorScriptComponent.code,
        kwargs=asdict(exec_act_kwargs),
    )
    #  spider 没有主从节点.指定备份的ip:port为主节点。
    cluster["master_ip"] = ""
    cluster["master_port"] = 0
    cluster["change_master"] = False
    backup_info = cluster["backupinfo"]
    cluster["backup_time"] = backup_info["backup_time"]
    # 是否有前滚binlog。spider没有binlog。所以不需要前滚binlog
    cluster["recover_binlog"] = False
    task_ids = [i["task_id"] for i in backup_info["file_list_details"]]
    download_kwargs = DownloadBackupFileKwargs(
        bk_cloud_id=cluster["bk_cloud_id"],
        task_ids=task_ids,
        dest_ip=cluster["rollback_ip"],
        dest_dir=cluster["file_target_path"],
        reason="spider node rollback data",
    )
    sub_pipeline.add_act(
        act_name=_("下载定点恢复的全库备份介质到{}:{}").format(cluster["rollback_ip"], cluster["rollback_port"]),
        act_component_code=MySQLDownloadBackupfileComponent.code,
        kwargs=asdict(download_kwargs),
    )
    exec_act_kwargs.exec_ip = cluster["rollback_ip"]
    exec_act_kwargs.job_timeout = MYSQL_DATA_RESTORE_TIME
    exec_act_kwargs.get_mysql_payload_func = MysqlActPayload.get_rollback_data_restore_payload.__name__
    sub_pipeline.add_act(
        act_name=_("定点恢复之恢复数据{}:{}").format(exec_act_kwargs.exec_ip, cluster["rollback_port"]),
        act_component_code=ExecuteDBActuatorScriptComponent.code,
        kwargs=asdict(exec_act_kwargs),
    )
    # 因为目前 spider 没有binlog，and False 先屏蔽掉日志前滚流程
    if cluster["rollback_type"] == RollbackType.REMOTE_AND_TIME.value and False:
        spider_has_binlog = cluster.get("spider_has_binlog", False)
        if spider_has_binlog:
            binlog_result = get_backup_binlog(
                cluster_id=cluster["cluster_id"],
                start_time=str2datetime(backup_info["backup_time"]),
                end_time=str2datetime(cluster["rollback_time"]),
                binlog_info=backup_info["binlog_info"],
            )
            if "query_binlog_error" in binlog_result.keys():
                raise TendbGetBinlogFailedException(message=binlog_result["query_binlog_error"])

            cluster_ins = copy.deepcopy(cluster)
            cluster_ins.update(binlog_result)
            download_kwargs = DownloadBackupFileKwargs(
                bk_cloud_id=cluster["bk_cloud_id"],
                task_ids=binlog_result["binlog_task_ids"],
                dest_ip=cluster_ins["rollback_ip"],
                dest_dir=cluster_ins["file_target_path"],
                reason="spider node rollback binlog",
            )
            sub_pipeline.add_act(
                act_name=_("下载定点恢复的binlog到{}:{}").format(cluster["rollback_ip"], cluster["rollback_port"]),
                act_component_code=MySQLDownloadBackupfileComponent.code,
                kwargs=asdict(download_kwargs),
            )

            exec_act_kwargs.exec_ip = cluster["rollback_ip"]
            exec_act_kwargs.cluster = copy.deepcopy(cluster_ins)
            exec_act_kwargs.get_mysql_payload_func = MysqlActPayload.tendb_recover_binlog_payload.__name__
            sub_pipeline.add_act(
                act_name=_("定点恢复之前滚binlog{}:{}").format(exec_act_kwargs.exec_ip, cluster["rollback_port"]),
                act_component_code=ExecuteDBActuatorScriptComponent.code,
                kwargs=asdict(exec_act_kwargs),
            )

    return sub_pipeline.build_sub_process(sub_name=_("spider恢复:{}".format(cluster["instance"])))


def remote_node_rollback(root_id: str, ticket_data: dict, cluster: dict):
    """
    remote node 主从节点数据恢复+binlog前滚 备份类型 rollback_type 分为2种:
    REMOTE_AND_TIME:指定时间点恢复。恢复备份文件+binlog前滚
    REMOTE_AND_BACKUPID:指定备份id恢复。只需恢复备份文件
    @param root_id: flow 流程 root_id
    @param ticket_data: 关联单据 ticket对象
    @param cluster: 关联的cluster对象
    """
    sub_pipeline_all = SubBuilder(root_id=root_id, data=ticket_data)
    sub_pipeline_all_list = []
    instance_check_list = []
    backup_info = cluster["backupinfo"]
    if cluster["new_master"]["instance"] != cluster["new_slave"]["instance"] and cluster["all_database_rollback"]:
        sub_pipeline_all.add_act(
            act_name=_("从库stop slave {}").format(cluster["new_slave"]["instance"]),
            act_component_code=MySQLExecuteRdsComponent.code,
            kwargs=asdict(
                ExecuteRdsKwargs(
                    bk_cloud_id=int(cluster["bk_cloud_id"]),
                    instance_ip=cluster["new_slave"]["ip"],
                    instance_port=cluster["new_slave"]["port"],
                    sqls=["stop slave"],
                )
            ),
        )
    for node in [cluster["new_master"], cluster["new_slave"]]:
        if node["instance"] in instance_check_list:
            continue
        instance_check_list.append(node["instance"])
        cluster["rollback_ip"] = node["ip"]
        cluster["rollback_port"] = node["port"]
        cluster["backup_time"] = backup_info["backup_time"]
        if cluster["rollback_type"] == RollbackType.REMOTE_AND_TIME.value:
            cluster["recover_binlog"] = True
        else:
            cluster["recover_binlog"] = False

        sub_pipeline = SubBuilder(root_id=root_id, data=ticket_data)
        exec_act_kwargs = ExecActuatorKwargs(
            bk_cloud_id=int(cluster["bk_cloud_id"]),
            cluster_type=ClusterType.TenDBCluster,
            cluster=copy.deepcopy(cluster),
        )
        exec_act_kwargs.get_mysql_payload_func = MysqlActPayload.mysql_mkdir_dir.__name__
        exec_act_kwargs.exec_ip = cluster["rollback_ip"]
        sub_pipeline.add_act(
            act_name=_("创建目录 {}".format(cluster["file_target_path"])),
            act_component_code=ExecuteDBActuatorScriptComponent.code,
            kwargs=asdict(exec_act_kwargs),
        )

        task_ids = [i["task_id"] for i in backup_info["file_list_details"]]
        # 是否回档从库？
        download_kwargs = DownloadBackupFileKwargs(
            bk_cloud_id=cluster["bk_cloud_id"],
            task_ids=task_ids,
            dest_ip=cluster["rollback_ip"],
            dest_dir=cluster["file_target_path"],
            reason="spider remote node rollback data",
        )
        sub_pipeline.add_act(
            act_name=_("下载定点恢复的全库备份介质到{}:{}".format(cluster["rollback_ip"], cluster["rollback_port"])),
            act_component_code=MySQLDownloadBackupfileComponent.code,
            kwargs=asdict(download_kwargs),
        )
        exec_act_kwargs.exec_ip = cluster["rollback_ip"]
        exec_act_kwargs.job_timeout = MYSQL_DATA_RESTORE_TIME
        exec_act_kwargs.get_mysql_payload_func = MysqlActPayload.get_rollback_data_restore_payload.__name__
        sub_pipeline.add_act(
            act_name=_("定点恢复之恢复数据{}:{}".format(exec_act_kwargs.exec_ip, cluster["rollback_port"])),
            act_component_code=ExecuteDBActuatorScriptComponent.code,
            kwargs=asdict(exec_act_kwargs),
            write_payload_var="change_master_info",
        )
        #  指定时间点的定点回档则需要执行binlog前滚。滚动到指定的时间点。

        if cluster["rollback_type"] == RollbackType.REMOTE_AND_TIME.value:
            binlog_result = get_backup_binlog(
                cluster_id=cluster["cluster_id"],
                start_time=str2datetime(backup_info["backup_time"]),
                end_time=str2datetime(cluster["rollback_time"]),
                binlog_info=backup_info["binlog_info"],
            )
            if "query_binlog_error" in binlog_result.keys():
                raise TendbGetBinlogFailedException(message=binlog_result["query_binlog_error"])

            cluster_ins = copy.deepcopy(cluster)
            cluster_ins.update(binlog_result)
            download_kwargs = DownloadBackupFileKwargs(
                bk_cloud_id=cluster["bk_cloud_id"],
                task_ids=binlog_result["binlog_task_ids"],
                dest_ip=cluster_ins["rollback_ip"],
                dest_dir=cluster_ins["file_target_path"],
                reason="tenDB rollback binlog",
            )
            sub_pipeline.add_act(
                act_name=_("下载定点恢复的binlog到{}:{}".format(cluster["rollback_ip"], cluster["rollback_port"])),
                act_component_code=MySQLDownloadBackupfileComponent.code,
                kwargs=asdict(download_kwargs),
            )
            exec_act_kwargs.exec_ip = cluster["rollback_ip"]
            exec_act_kwargs.cluster = copy.deepcopy(cluster_ins)
            exec_act_kwargs.get_mysql_payload_func = MysqlActPayload.tendb_recover_binlog_payload.__name__
            sub_pipeline.add_act(
                act_name=_("定点恢复之前滚binlog{}:{}".format(exec_act_kwargs.exec_ip, cluster["rollback_port"])),
                act_component_code=ExecuteDBActuatorScriptComponent.code,
                kwargs=asdict(exec_act_kwargs),
            )
        sub_pipeline_all_list.append(
            sub_pipeline.build_sub_process(sub_name=_("定点恢复 {}:{}".format(node["ip"], node["port"])))
        )
        # 针对slave repeater角色的从库。建立复制链路。重置slave>添加复制账号和获取位点>建立主从关系
    sub_pipeline_all.add_parallel_sub_pipeline(sub_pipeline_all_list)
    backup_type = backup_info.get("backup_type", "")
    # backup_type = MySQLBackupTypeEnum.PHYSICAL.value
    if cluster["new_master"]["instance"] != cluster["new_slave"]["instance"]:
        if backup_type == MySQLBackupTypeEnum.PHYSICAL.value:
            repl_cluster = {
                "target_ip": cluster["new_master"]["ip"],
                "target_port": cluster["new_master"]["port"],
                "repl_ip": cluster["new_slave"]["ip"],
                "repl_port": cluster["new_slave"]["port"],
                "change_master_type": MysqlChangeMasterType.MASTERSTATUS.value,
                "change_master_force": True,
            }
            repl_exec_act_kwargs = ExecActuatorKwargs(
                bk_cloud_id=cluster["bk_cloud_id"],
                cluster_type=ClusterType.TenDBCluster,
                cluster=copy.deepcopy(repl_cluster),
                job_timeout=MYSQL_USUAL_JOB_TIME,
            )
            repl_exec_act_kwargs.exec_ip = cluster["new_master"]["ip"]
            repl_exec_act_kwargs.get_mysql_payload_func = MysqlActPayload.tendb_grant_remotedb_repl_user.__name__
            sub_pipeline_all.add_act(
                act_name=_("新增repl帐户{}".format(repl_exec_act_kwargs.exec_ip)),
                act_component_code=ExecuteDBActuatorScriptComponent.code,
                kwargs=asdict(repl_exec_act_kwargs),
                write_payload_var="show_master_status_info",
            )
            #  启动，或者建立组从关系
            repl_exec_act_kwargs.exec_ip = cluster["new_slave"]["ip"]
            repl_exec_act_kwargs.get_mysql_payload_func = MysqlActPayload.tendb_remotedb_change_master.__name__
            sub_pipeline_all.add_act(
                act_name=_("建立原主从关系{}".format(cluster["new_slave"]["instance"])),
                act_component_code=ExecuteDBActuatorScriptComponent.code,
                kwargs=asdict(repl_exec_act_kwargs),
            )

        elif backup_type == MySQLBackupTypeEnum.LOGICAL.value:
            sub_pipeline_all.add_act(
                act_name=_("从库start slave {}").format(cluster["new_slave"]["instance"]),
                act_component_code=MySQLExecuteRdsComponent.code,
                kwargs=asdict(
                    ExecuteRdsKwargs(
                        bk_cloud_id=cluster["bk_cloud_id"],
                        instance_ip=cluster["new_slave"]["ip"],
                        instance_port=cluster["new_slave"]["port"],
                        sqls=["start slave"],
                    )
                ),
            )
    return sub_pipeline_all.build_sub_process(
        sub_name=_(
            "Remote node {} 恢复: 主 {} 从 {} ".format(
                cluster["shard_id"], cluster["new_master"]["instance"], cluster["new_slave"]["instance"]
            )
        )
    )
