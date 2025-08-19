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
import uuid
from typing import Any, Dict, Type
from unittest.mock import PropertyMock, patch

import pytest
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.test import APIClient

from backend.configuration.handlers.password import DBPasswordHandler
from backend.core import notify
from backend.tests.mock_data.components.cc import CCApiMock
from backend.tests.mock_data.components.dbresource import DBResourceApiMock
from backend.tests.mock_data.components.engine_run_pipeline import EngineApiMock
from backend.tests.mock_data.components.itsm import ItsmApiMock
from backend.tests.mock_data.components.mysql_priv_manager import DBPrivManagerApiMock
from backend.tests.mock_data.components.nodeman import NodemanApiMock
from backend.tests.mock_data.iam_app.permission import PermissionMock
from backend.tests.mock_data.ticket.ticket_flow import PASSWORD, ROOT_ID
from backend.ticket.constants import TicketFlowStatus, TicketStatus
from backend.ticket.flow_manager.inner import InnerFlow
from backend.ticket.flow_manager.pause import PauseFlow
from backend.ticket.handler import TicketHandler
from backend.ticket.models import ClusterOperateRecordManager, Ticket, TicketFlowsConfig
from backend.ticket.views import TicketViewSet

pytestmark = pytest.mark.django_db


class BaseTicketTest:
    """
    测试流程的基类。
    """

    # 默认单据测试的patch
    patches = [
        patch.object(TicketViewSet, "permission_classes", return_value=[AllowAny]),
        patch.object(InnerFlow, "_run", return_value=ROOT_ID),
        patch.object(InnerFlow, "status", new_callable=PropertyMock, return_value=TicketStatus.SUCCEEDED),
        patch.object(PauseFlow, "status", new_callable=PropertyMock, return_value=TicketFlowStatus.SKIPPED),
        patch.object(DBPasswordHandler, "get_random_password", return_value=PASSWORD),
        patch.object(notify.send_msg, "apply_async", return_value="this is a test msg"),
        patch.object(TicketViewSet, "get_permissions"),
        patch.object(settings, "MIDDLEWARE", return_value=[]),
        patch.object(ClusterOperateRecordManager, "get_exclusive_ticket_map", return_value=[]),
        patch("backend.ticket.flow_manager.itsm.ItsmApi", ItsmApiMock()),
        patch("backend.db_services.cmdb.biz.Permission", PermissionMock),
        patch("backend.ticket.flow_manager.resource.DBResourceApi", DBResourceApiMock),
        patch("backend.db_services.dbresource.handlers.CCApi", CCApiMock()),
        patch("backend.db_services.cmdb.biz.CCApi", CCApiMock()),
        patch("backend.db_services.ipchooser.query.resource.CCApi", CCApiMock()),
        patch("backend.db_services.ipchooser.query.resource.BKNodeManApi", NodemanApiMock()),
        patch("backend.configuration.handlers.password.DBPrivManagerApi", DBPrivManagerApiMock()),
        patch("backend.db_services.dbpermission.db_account.handlers.DBPrivManagerApi", DBPrivManagerApiMock()),
    ]
    # 默认测试请求客户端
    client = APIClient()
    # 默认单据配置
    ticket_config_map = {}

    @classmethod
    def apply_patches(cls):
        [patcher.start() for patcher in cls.patches]

    @classmethod
    def stop_patches(cls):
        [patcher.stop() for patcher in cls.patches]

    @pytest.fixture(scope="class", autouse=True)
    def setup_class(self, django_db_setup, django_db_blocker):
        """
        测试类的初始化(替换原 setUpClass 的类级别初始化)
        """
        with django_db_blocker.unblock():
            # 初始化单据配置
            TicketHandler.ticket_flow_config_init()
            self.ticket_config_map = {config.ticket_type: config.configs for config in TicketFlowsConfig.objects.all()}

            # 启动所有 Mock
            self.apply_patches()

            # 初始化客户端并登录
            self.client = APIClient()
            self.client.login(username="admin")

            yield

            # 停止 Mock
            self.stop_patches()

    @pytest.fixture(autouse=True)
    def setup_test(self):
        """测试方法的初始设置(替换原 setUp/tearDown)"""
        yield

    def flow_test(self, ticket_data, flow_class=None, flow_method=None, additional_params=None):
        """
        基本的单据测试，只看单据是否能跑通
        """
        itsm_data = copy.deepcopy(ticket_data)
        resp = self.client.post("/apis/tickets/", data=itsm_data)
        assert status.is_success(resp.status_code)
        ticket = Ticket.objects.get(id=resp.data["id"])
        # 只有在提供了 flow_class 和 flow_method 时才执行后续流程测试
        if flow_class and flow_method:
            resp2 = self.client.get(f"/apis/tickets/{ticket.id}/flows/")
            assert status.is_success(resp2.status_code), f"获取单据流程失败: {resp2.status_code}"
            flow_data = resp2.json()
            for data in flow_data["data"]:
                if data["flow_type"] == "INNER_FLOW":
                    data["details"]["ticket_data"]["create_by"] = "admin"
                    params = data["details"]["ticket_data"]
            self.execute_pipeline_test(
                root_id=uuid.uuid4().hex[:24],
                mock_data=params,
                flow_class=flow_class,
                flow_method=flow_method,
                additional_params=additional_params,
            )
        current_flow = None

        while ticket.next_flow() is not None:
            last_flow, current_flow = current_flow, ticket.current_flow()
            assert not last_flow or (last_flow and last_flow.id != current_flow.id), f"flow[{current_flow.id}]流转失败"

            resp = self.client.post(f"/apis/tickets/{current_flow.ticket_id}/callback/")
            assert status.is_success(resp.status_code), f"response 请求错误: {resp.status_code}"

    def execute_pipeline_test(
        self,
        root_id: str,
        flow_class: Type,
        flow_method: str,
        additional_params: Dict[str, Any] = None,
        mock_data: Dict[str, Any] = None,
        expect_failure: bool = False,
        expected_error_message: str = None,
    ) -> Any:
        """
        执行流程测试

        Args:
            root_id: 流程根ID
            flow_class: 流程类
            flow_method: 要测试的流程方法名称
            additional_params: 额外需要的参数
            mock_data: 自定义参数，会覆盖默认参数
            expect_failure: 是否期望Pipeline验证失败
            expected_error_message: 期望的错误消息，如果expect_failure为True，则可以指定期望的错误消息

        Returns:
            Any: 流程方法的返回值
        """

        # 创建流程实例
        flow_instance = flow_class(root_id=root_id, data=mock_data, **(additional_params or {}))

        # 重置EngineApiMock的状态
        EngineApiMock.was_called = False
        EngineApiMock.last_result = None
        EngineApiMock.last_exception = None

        # 准备所有需要模拟的对象
        # 仅添加pipeline mock，其他所有mock都在类级别的patches中定义
        patchers = []

        # 添加默认的pipeline mock
        pipeline_patch = patch("bamboo_engine.api.run_pipeline", side_effect=EngineApiMock.run_pipeline)
        patchers.append(pipeline_patch)

        # 启动所有局部patchers
        [patcher.start() for patcher in patchers]

        try:
            # 获取要测试的方法
            flow_method_to_test = getattr(flow_instance, flow_method)

            # 执行流程方法（可能返回None，即使成功）
            result = flow_method_to_test()

            # 检查EngineApiMock是否被调用
            assert EngineApiMock.was_called, "Pipeline engine should be called"

            # 验证执行结果
            if expect_failure:
                assert EngineApiMock.last_result.result, "Pipeline validation should fail"
                if expected_error_message:
                    assert expected_error_message in EngineApiMock.last_result.message, (
                        f"Expected error message '{expected_error_message}' not found in actual message: "
                        f"'{EngineApiMock.last_result.message}'"
                    )

            else:
                assert (
                    EngineApiMock.last_result.result
                ), f"Pipeline validation should pass, but failed with message: {EngineApiMock.last_result.message}"

            return result

        except Exception as e:
            if expect_failure:
                if expected_error_message:
                    assert expected_error_message in str(
                        e
                    ), f"Expected error message '{expected_error_message}' not found in actual exception: '{str(e)}'"
                return None
            else:
                raise
        finally:
            # 停止所有patchers
            for patcher in patchers:
                patcher.stop()
