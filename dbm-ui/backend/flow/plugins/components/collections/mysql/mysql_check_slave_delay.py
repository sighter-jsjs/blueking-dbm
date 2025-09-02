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
import time

from django.utils.translation import ugettext as _
from pipeline.component_framework.component import Component

from backend.components import DRSApi
from backend.constants import IP_PORT_DIVIDER
from backend.flow.plugins.components.collections.common.base_service import BaseService

logger = logging.getLogger("flow")


class MySQLCheckSlaveDelayService(BaseService):
    """
    执行 show slave status 语句
    """

    def _execute(self, data, parent_data) -> bool:
        kwargs = data.get_one_of_inputs("kwargs")
        self.log_info(_("传入参数:{}").format(kwargs))
        self.log_info(_("检查从库是否延迟,如果检查不通过,根据您实际需求来选择跳过此节点。"))
        rounds = kwargs.get("rounds", 1)
        for i in range(rounds):
            self.log_info(_("第{}次检查从库是否延迟".format(i + 1)))
            time.sleep(10)
            res = DRSApi.rpc(
                {
                    "addresses": ["{}{}{}".format(kwargs["instance_ip"], IP_PORT_DIVIDER, kwargs["instance_port"])],
                    "cmds": ["show slave status"],
                    "force": False,
                    "bk_cloud_id": kwargs["bk_cloud_id"],
                }
            )
            if res[0]["error_msg"]:
                self.log_info("execute sql error {}".format(res[0]["error_msg"]))
                return False
            else:
                if len(res[0]["cmd_results"][0]["table_data"]) == 0:
                    self.log_info("show slave status is empty")
                    return False
                else:
                    slave_info = res[0]["cmd_results"][0]["table_data"][0]
                    slave_delay = 0

                    if kwargs["master_ip"] != "" or int(kwargs["master_port"]) != 0:
                        if slave_info["Master_Host"] != kwargs["master_ip"] or int(slave_info["Master_Port"]) != int(
                            kwargs["master_port"]
                        ):
                            self.log_info(_("请确定实例对应的主节点是否正确"))
                            return False

                    if slave_info["Seconds_Behind_Master"] is not None:
                        slave_delay = int(slave_info["Seconds_Behind_Master"])
                    if (
                        slave_info["Slave_IO_Running"] == "Yes"
                        and slave_info["Slave_SQL_Running"] == "Yes"
                        and slave_delay <= kwargs["slave_delay_threshold"]
                    ):
                        return True
                    else:
                        self.log_info(
                            _(
                                "Slave_IO_Running!=Yes or Slave_SQL_Running=!Yes or Seconds_Behind_Master>300,"
                                "请确定slave复制链路正常且延迟不能超过300s。"
                            )
                        )
                        return False


class MySQLCheckSlaveDelayComponent(Component):
    name = __name__
    code = "mysql_check_slave_delay"
    bound_service = MySQLCheckSlaveDelayService
