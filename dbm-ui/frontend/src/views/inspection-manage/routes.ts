/*
 * TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-DB管理系统(BlueKing-BK-DBM) available.
 *
 * Copyright (C) 2017-2023 THL A29 Limited, a Tencent company. All rights reserved.
 *
 * Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at https://opensource.org/licenses/MIT
 *
 * Unless required by applicable law or agreed to in writing, software distributed under the License is distributed
 * on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for
 * the specific language governing permissions and limitations under the License.
 */
import { registerBusinessModule, registerModule } from '@router';

import { checkDbConsole } from '@utils';

import { t } from '@locales/index';

export default function getRoutes() {
  registerModule([
    {
      path: 'inspection-todos',
      name: 'InspectionTodos',
      meta: {
        fullscreen: true,
        navName: t('巡检待办'),
      },
      component: () => import('@views/inspection-manage/todo/Index.vue'),
    },
    {
      path: 'inspection-report-global',
      name: 'inspectionReportGlobal',
      meta: {
        fullscreen: true,
        navName: t('巡检报告'),
      },
      component: () => import('@views/inspection-manage/report/Index.vue'),
    },
  ]);
  if (checkDbConsole('observableManage.healthReport')) {
    registerBusinessModule([
      {
        path: 'inspection-manage',
        name: 'inspectionManage',
        meta: {
          navName: t('巡检'),
        },
        redirect: {
          name: 'inspectionReport',
        },
        component: () => import('@views/inspection-manage/Index.vue'),
        children: [
          {
            path: 'report',
            name: 'inspectionReport',
            meta: {
              fullscreen: true,
              navName: t('巡检报告'),
            },
            component: () => import('@views/inspection-manage/report/Index.vue'),
          },
        ],
      },
    ]);
  }
}
