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
import logging
from typing import List

from django.utils.translation import ugettext as _
from pipeline.component_framework.component import Component
from pipeline.core.flow.activity import Service

from backend import env
from backend.components.mysql_priv_manager.client import DBPrivManagerApi
from backend.db_services.mysql.permission.clone.models import MySQLPermissionCloneRecord
from backend.db_services.mysql.permission.constants import CloneType
from backend.flow.consts import UserName
from backend.flow.plugins.components.collections.common.base_service import BaseService

logger = logging.getLogger("flow")


class CloneRules(BaseService):
    """根据克隆表单数据进行权限克隆"""

    # @staticmethod
    def _clone_rule(
        self,
        bk_biz_id,
        clone_cluster_type,
        clone_type,
        operator,
        clone_data,
        inst_machine_type_map,
        uid,
    ):
        # 权限克隆全局参数准备
        params = {
            "bk_biz_id": bk_biz_id,
            "operator": operator,
            "bk_cloud_id": clone_data["bk_cloud_id"],
            "cluster_type": clone_cluster_type,
            "system_users": [
                *UserName.get_values(),
                "gcs_dba",
            ],
            **self.extra_log,
            "uid": "{}".format(uid),
        }
        try:
            # 调用客户端克隆/实例克隆
            if clone_type == CloneType.CLIENT.value:
                params.update({"source_ip": clone_data["source"], "target_ip": clone_data["target"]})
                if "user" in clone_data and "target_instances" in clone_data:
                    params.update({"user": clone_data["user"], "target_instances": clone_data["target_instances"]})
                resp = DBPrivManagerApi.clone_client(params=params, raw=True, timeout=DBPrivManagerApi.TIMEOUT)
            else:

                params.update(
                    {
                        "source": {
                            "address": clone_data["source"],
                            "machine_type": inst_machine_type_map[clone_data["source"]],
                        },
                        "target": {
                            "address": clone_data["target"],
                            "machine_type": inst_machine_type_map[clone_data["target"]],
                        },
                    }
                )
                resp = DBPrivManagerApi.clone_instance_v2(params=params, raw=True, timeout=DBPrivManagerApi.TIMEOUT)
            clone_result = {"code": resp["code"], "message": resp["message"]}
        except Exception as e:  # pylint: disable=broad-except
            error_message = _("权限克隆异常: {}").format(getattr(e, "message", e))
            clone_result = {"code": -1, "message": error_message}

        return clone_result

    def _execute(self, data, parent_data, callback=None) -> bool:
        kwargs = data.get_one_of_inputs("kwargs")
        global_data = data.get_one_of_inputs("global_data")
        ticket_id = kwargs["uid"]
        bk_biz_id = kwargs["bk_biz_id"]
        operator = kwargs["operator"]
        clone_type = kwargs["clone_type"]
        clone_cluster_type = kwargs["clone_cluster_type"]
        clone_data = kwargs["clone_data"]
        inst_machine_type_map = kwargs.get("inst_machine_type_map")

        # 权限克隆
        resp = self._clone_rule(
            bk_biz_id,
            clone_cluster_type,
            clone_type,
            operator,
            clone_data,
            inst_machine_type_map,
            global_data.get("uid", "0"),  # 保持是字符串
        )
        # 实例化权限克隆记录，后续存到数据库中
        record = MySQLPermissionCloneRecord(
            ticket_id=ticket_id,
            bk_cloud_id=clone_data["bk_cloud_id"],
            source=clone_data["source"],
            target=clone_data["target"],
            clone_type=clone_type,
            status=int(resp["code"]) == 0,
            error=resp["message"],
        )
        if clone_type == CloneType.CLIENT.value:
            record.target = "\n".join(record.target)
        record.save()

        # 打印授权结果
        self.log_info(_("授权结果: {}").format(resp["message"]))
        self.log_info(
            _(
                "详情请下载excel: <a href='{}/apis/mysql/bizs/{}/permission/clone/"
                "get_clone_info_excel/?ticket_id={}&clone_type={}'>excel 下载</a>"
            ).format(env.BK_SAAS_HOST, bk_biz_id, ticket_id, clone_type)
        )
        return record.status

    def inputs_format(self) -> List:
        return [Service.InputItem(name="kwargs", key="kwargs", type="dict", required=True)]


class CloneRulesComponent(Component):
    name = __name__
    code = "clone_rules"
    bound_service = CloneRules
