"""
TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-DB管理系统(BlueKing-BK-DBM) available.
Copyright (C) 2017-2023 THL A29 Limited, a Tencent company. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
You may obtain a copy of the License at https://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
"""


import logging

from django.utils.translation import ugettext as _
from pipeline.component_framework.component import Component

from backend.components import DRSApi
from backend.db_meta.enums import InstanceStatus
from backend.db_meta.exceptions import ClusterNotExistException
from backend.db_meta.models import Cluster
from backend.flow.plugins.components.collections.common.base_service import BaseService
from backend.flow.utils.mysql.common.random_job_with_ticket_map import (
    TICKET_TYPE_SENSITIVE_LIST,
    get_instance_with_random_job,
)
from backend.flow.utils.mysql.get_mysql_sys_user import generate_mysql_tmp_user
from backend.flow.utils.mysql.mysql_version_parse import mysql_version_parse
from backend.ticket.constants import TicketType

logger = logging.getLogger("flow")


class DropTempUserForClusterService(BaseService):
    """
    为单据删除job的临时本地账号，操作目标实例
    单据是以集群维度来删除
    """

    def drop_jor_user(self, cluster: Cluster, root_id: str, ticket_type: TicketType):
        """
        集群维度删除job的临时用户
        """
        # 拼接临时用户的名称
        user = generate_mysql_tmp_user(root_id)
        is_drop_success = True
        # 删除localhost和 local_ip用户
        payloads = []
        not_running_status_instances = []
        for instance in get_instance_with_random_job(cluster=cluster, ticket_type=ticket_type):
            # 默认先关闭binlog记录， 最后统一打开
            cmd = ["set session sql_log_bin = 0 ;"]

            self.log_info(f"the cluster version is {cluster.major_version}")
            if mysql_version_parse(cluster.major_version) >= mysql_version_parse("5.7"):
                cmd += [
                    f"drop user if exists `{user}`@`localhost`;",
                    f"drop user if exists `{user}`@`{instance['instance'].split(':')[0]}`;",
                ]
            else:
                cmd += [
                    f"drop user `{user}`@`localhost`;",
                    f"drop user `{user}`@`{instance['instance'].split(':')[0]}`;",
                ]
            # 最后统一打开binlog, 避免复用异常
            cmd.append("set session sql_log_bin = 1 ;")
            payloads.append(
                {
                    "addresses": [instance["instance"]],
                    "cmds": cmd,
                    "force": True,  # 中间出错也要执行下去，保证重新打开binlog
                    "bk_cloud_id": cluster.bk_cloud_id,
                }
            )
            if instance["cmdb_status"] != InstanceStatus.RUNNING:
                not_running_status_instances.append(instance["instance"])

        resp = DRSApi.mysql_complex_rpc(
            {
                "payloads": payloads,
                "bk_cloud_id": cluster.bk_cloud_id,
            }
        )
        for result in resp:
            err_list = []
            if result["cmd_results"]:
                err_list = [i["error_msg"] for i in result["cmd_results"] if i["error_msg"]]

            if result["error_msg"] or err_list:
                # 如果是执行失败，则判断下面，同时输出日志
                error_log = "\n".join([result["error_msg"]] + err_list)
                if result["address"] in not_running_status_instances and ticket_type not in TICKET_TYPE_SENSITIVE_LIST:
                    # 如果是非running状态，标记warning信息，但不作异常处理
                    self.log_error(error_log)
                    self.log_warning(f"[{result['address']} is not running in dbm ,ignore]")
                    continue

                # 如果实例是running状态，应该记录错误，并且返回异常
                # 如果实例非running状态，且单据类型加入敏感队列，则需要记录错误，并且返回异常
                self.log_error(f"The result [drop user `{user}`] in {result['address']} error is: [{error_log}]")
                is_drop_success = False

            self.log_info(f"The result [drop user `{user}`] in {result['address']} is [success]")

        if not is_drop_success:
            self.log_error(f"drop user error in cluster [{cluster.immute_domain}]")
            return False

        self.log_info(f"drop user finish in cluster [{cluster.immute_domain}]")
        return True

    def _execute(self, data, parent_data, callback=None) -> bool:
        kwargs = data.get_one_of_inputs("kwargs")
        global_data = data.get_one_of_inputs("global_data")
        is_err = False
        for cluster_id in kwargs["cluster_ids"]:
            # 获取每个cluster_id对应的对象
            try:
                cluster = Cluster.objects.get(id=cluster_id, bk_biz_id=global_data["bk_biz_id"])
            except Cluster.DoesNotExist:
                raise ClusterNotExistException(
                    cluster_id=cluster_id, bk_biz_id=global_data["bk_biz_id"], message=_("集群不存在")
                )
            if not self.drop_jor_user(
                cluster=cluster, root_id=global_data["job_root_id"], ticket_type=global_data.get("ticket_type", "test")
            ):
                # 删除账号不成功
                is_err = True

        if is_err:
            return False

        return True


class DropTempUserForClusterComponent(Component):
    name = __name__
    code = "drop_job_temp_user"
    bound_service = DropTempUserForClusterService
