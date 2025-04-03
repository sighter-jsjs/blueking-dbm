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
from django.utils.translation import ugettext_lazy as _
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from backend.bk_web import viewsets
from backend.bk_web.swagger import common_swagger_auto_schema
from backend.configuration.constants import ProfileLabel
from backend.configuration.models import DBAdministrator, Profile
from backend.configuration.serializers import ProfileSerializer, ProfileSqlSerializer
from backend.iam_app.dataclass.actions import ActionEnum
from backend.iam_app.handlers.permission import Permission

SWAGGER_TAG = _("个人配置")


class ProfileViewSet(viewsets.SystemViewSet):
    serializer_class = ProfileSerializer
    default_permission_class = []

    @common_swagger_auto_schema(operation_summary=_("查询个人配置列表"), tags=[SWAGGER_TAG])
    @action(methods=["GET"], detail=False)
    def get_profile(self, request, *args, **kwargs):
        username = request.user.username
        # 鉴权资源管理和平台管理
        client = Permission()
        resource_manage = client.is_allowed(action=ActionEnum.RESOURCE_MANAGE, resources=[])
        global_manage = client.is_allowed(action=ActionEnum.GLOBAL_MANAGE, resources=[])
        platform_manage = client.is_allowed(action=ActionEnum.PLATFORM_MANAGE, resources=[])
        # 排除个人配置SQL，只用于DB查询没必要全量返回
        profile = Profile.objects.filter(username=username).exclude(label=ProfileLabel.SQL).values("label", "values")
        return Response(
            {
                "resource_manage": resource_manage,
                "global_manage": global_manage,
                "platform_manage": platform_manage,
                "username": username,
                "profile": list(profile),
                "is_superuser": request.user.is_superuser,
                "is_dba": DBAdministrator.is_dba(request.user.username),
            }
        )

    @common_swagger_auto_schema(operation_summary=_("新增/更新个人配置"), tags=[SWAGGER_TAG])
    @action(methods=["POST"], detail=False, serializer_class=ProfileSerializer)
    def upsert_profile(self, request, *args, **kwargs):
        validated_data = self.params_validate(self.get_serializer_class())
        Profile.objects.update_or_create(
            defaults={"values": validated_data["values"]},
            username=request.user.username,
            label=validated_data["label"],
        )
        return Response()

    @common_swagger_auto_schema(
        operation_summary=_("查询个人收藏SQL"), tags=[SWAGGER_TAG], responses={status.HTTP_200_OK: ProfileSqlSerializer()}
    )
    @action(methods=["GET"], detail=False)
    def get_profile_sql(self, request, *args, **kwargs):
        try:
            sql_profile = Profile.objects.get(username=request.user.username, label=ProfileLabel.SQL)
            return Response(sql_profile.values)
        except Profile.DoesNotExist:
            return Response(data={})
