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
from backend.db_meta.exceptions import ClusterNotExistException
from backend.db_meta.models import Cluster, StorageInstance
from backend.flow.plugins.components.collections.common.base_service import BaseService
from backend.flow.utils.mysql.mysql_commom_query import pre_check_proxy_host_in_definer, show_user_host_for_host

logger = logging.getLogger("flow")


class DropProxyUsersInBackendService(BaseService):
    """
    在集群内清理旧proxy的后端权限
    """

    def pre_check_proxy_host_in_definer(self, origin_proxy_host: str, backend: StorageInstance):
        """
        删除之前检查proxy的host，是否被definer配置应用到
        @param origin_proxy_host: 待检测host
        @param backend: 查询的backend实例
        """
        check_result = pre_check_proxy_host_in_definer(origin_proxy_host, backend)
        if check_result:
            # 表示该proxy_host 有对应的definer配置，返回 False
            for ret in check_result:
                self.log_error(f"[{origin_proxy_host}] dangerous definer-config exists :{ret}")
            return False

        self.log_info(f"[{origin_proxy_host}] pre-check passed")
        return True

    @staticmethod
    def drop_proxy_client(origin_proxy_host: str, backend: StorageInstance):
        """
        在backend删除proxy的权限, 删除之前需要做检查：旧proxy是否在backend有对应的definer配置
        @param origin_proxy_host: 待检测host
        @param backend: 查询的backend实例
        """

        result, user_hosts = show_user_host_for_host(host=origin_proxy_host, instance=backend)
        if not result:
            return False, f"[{backend.ip_port}] get user_host[{origin_proxy_host}] failed"

        # 执行删除旧proxy client
        if user_hosts:
            res = DRSApi.rpc(
                {
                    "addresses": [backend.ip_port],
                    "cmds": [f"drop user {i};" for i in user_hosts],
                    "force": False,
                    "bk_cloud_id": backend.machine.bk_cloud_id,
                }
            )
            if res[0]["error_msg"]:
                return (
                    False,
                    f"[{backend.ip_port}] drop old proxy client[{origin_proxy_host}] failed: [{res['error_msg']}]",
                )
        return True, ""

    def _execute(self, data, parent_data, callback=None) -> bool:
        kwargs = data.get_one_of_inputs("kwargs")
        global_data = data.get_one_of_inputs("global_data")
        try:
            cluster = Cluster.objects.get(id=kwargs["cluster_id"])
        except Cluster.DoesNotExist:
            raise ClusterNotExistException(
                cluster_id=kwargs["cluster_id"], bk_biz_id=int(global_data["bk_biz_id"]), message=_("集群不存在")
            )
        for s in cluster.storageinstance_set.all():
            if not self.pre_check_proxy_host_in_definer(kwargs["origin_proxy_host"], s):
                # 检测有高危的definer配置绑定到origin_proxy_host， 不做删除，跳过
                self.log_warning(
                    f"Cannot delete host [{kwargs['origin_proxy_host']}] privileges in backend [{s.ip_port}], skip"
                )
                continue

            status, err = self.drop_proxy_client(kwargs["origin_proxy_host"], s)
            if not status:
                self.log_error(err)
                return False
            self.log_info(f"[{s.ip_port}]drop old proxy client [{kwargs['origin_proxy_host']}] successfully")
        return True


class DropProxyUsersInBackendComponent(Component):
    name = __name__
    code = "drop_proxy_users_in_backend"
    bound_service = DropProxyUsersInBackendService
