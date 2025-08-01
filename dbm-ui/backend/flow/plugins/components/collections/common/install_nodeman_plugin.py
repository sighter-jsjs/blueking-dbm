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
import time

from django.utils.translation import gettext as _
from pipeline.component_framework.component import Component
from pipeline.core.flow import StaticIntervalGenerator

from backend import env
from backend.components import CCApi
from backend.components.bknodeman.client import BKNodeManApi
from backend.flow.plugins.components.collections.common.base_service import BaseService


class InstallNodemanPluginService(BaseService):
    """安装节点管理插件"""

    RETRY_ERROR_CODES = [502, 504]
    HTTP_STATUS_OK = 200

    __need_schedule__ = True
    interval = StaticIntervalGenerator(5)

    def _execute(self, data, parent_data):
        kwargs = data.get_one_of_inputs("kwargs")

        # bk_cloud_id + ips 组合，在这里获取bk_host_id
        if kwargs.get("ips"):
            ips = kwargs["ips"]
            bk_cloud_id = kwargs["bk_cloud_id"]
            # 获取对应的bk_host_id
            res = CCApi.list_hosts_without_biz(
                {
                    "fields": ["bk_host_id"],
                    "host_property_filter": {
                        "condition": "AND",
                        "rules": [
                            {"field": "bk_host_innerip", "operator": "in", "value": ips},
                            {"field": "bk_cloud_id", "operator": "equal", "value": bk_cloud_id},
                        ],
                    },
                },
                use_admin=True,
            )
            bk_host_ids = [host["bk_host_id"] for host in res["info"]]
        else:
            bk_host_ids = kwargs["bk_host_ids"]
        plugin_name = kwargs["plugin_name"]
        self.log_info(f"start installing {plugin_name} plugin")
        job = BKNodeManApi.operate_plugin(
            {"job_type": "MAIN_INSTALL_PLUGIN", "plugin_params": {"name": plugin_name}, "bk_host_id": bk_host_ids}
        )
        data.outputs.job_id = job["job_id"]
        self.log_info(_("安装插件任务: {}/#/task-list/detail/{}").format(env.BK_NODEMAN_URL, data.outputs.job_id))

    def _schedule(self, data, parent_data, callback_data=None):
        job_id = data.get_one_of_outputs("job_id")
        # 调用 API 并设置 raw=True, raise_exception=False，遇到特定错误码时重试
        max_retries = 3
        retry_count = 0
        while retry_count <= max_retries:
            # 使用 BKNodeManApi.job_details 的 _send 方法获取原始网络响应
            raw_response = BKNodeManApi.job_details._send(params={"job_id": job_id}, headers={})
            # 检查网络状态
            if raw_response.status_code == self.HTTP_STATUS_OK:
                # 网络请求成功，解析响应内容
                response = raw_response.json()
                break
            elif raw_response.status_code in self.RETRY_ERROR_CODES:
                retry_count += 1
                if retry_count <= max_retries:
                    time.sleep(5)  # 等待5秒再重试
                else:
                    self.log_error(
                        _("获取任务详情失败: {}").format(
                            f"code: {raw_response.status_code}, message: {raw_response.text or raw_response.reason}"
                        )
                    )
                    return False
            else:
                self.log_error(
                    _("获取任务详情失败: {}").format(
                        f"code: {raw_response.status_code}, message: {raw_response.text or raw_response.reason}"
                    )
                )
                return False
        status = response["data"]["status"]
        if status in BKNodeManApi.JobStatusType.PROCESSING_STATUS:
            self.log_info(f"installing plugin, job id is {job_id}")
            return True
        if status == BKNodeManApi.JobStatusType.SUCCESS:
            self.log_info("install plugin successfully")
            self.finish_schedule()
            return True
        else:
            self.log_error("install plugin failed")
            return False


class InstallNodemanPluginServiceComponent(Component):
    name = __name__
    code = "install_nodeman_plugin_service"
    bound_service = InstallNodemanPluginService
