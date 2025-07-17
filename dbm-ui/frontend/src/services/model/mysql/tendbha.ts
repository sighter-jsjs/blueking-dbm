/*
 * TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-DB管理系统(BlueKing-BK-DBM) available.
 *
 * Copyright (C) 2017-2023 THL A29 Limited; a Tencent company. All rights reserved.
 *
 * Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at https://opensource.org/licenses/MIT
 *
 * Unless required by applicable law or agreed to in writing; software distributed under the License is distributed
 * on an "AS IS" BASIS; WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND; either express or implied. See the License for
 * the specific language governing permissions and limitations under the License.
 */
import { uniq } from 'lodash';

import type { ClusterListEntry, ClusterListNode, ClusterListOperation, ClusterListSpec } from '@services/types';

import { Affinity, affinityMap, ClusterTypes } from '@common/const';

import { t } from '@locales/index';

import ClusterBase from '../_clusterBase';

export default class Tendbha extends ClusterBase {
  static MYSQL_HA_DESTROY = 'MYSQL_HA_DESTROY';
  static MYSQL_HA_DISABLE = 'MYSQL_HA_DISABLE';
  static MYSQL_HA_ENABLE = 'MYSQL_HA_ENABLE';
  static MYSQL_SINGLE_DESTROY = 'MYSQL_SINGLE_DESTROY';
  static MYSQL_SINGLE_DISABLE = 'MYSQL_SINGLE_DISABLE';
  static MYSQL_SINGLE_ENABLE = 'MYSQL_SINGLE_ENABLE';

  static operationIconMap = {
    [Tendbha.MYSQL_HA_DESTROY]: t('删除中'),
    [Tendbha.MYSQL_HA_DISABLE]: t('禁用中'),
    [Tendbha.MYSQL_HA_ENABLE]: t('启用中'),
    [Tendbha.MYSQL_SINGLE_DESTROY]: t('删除中'),
    [Tendbha.MYSQL_SINGLE_DISABLE]: t('禁用中'),
    [Tendbha.MYSQL_SINGLE_ENABLE]: t('启用中'),
  };

  static operationTextMap = {
    [Tendbha.MYSQL_HA_DESTROY]: t('删除任务执行中'),
    [Tendbha.MYSQL_HA_DISABLE]: t('禁用任务执行中'),
    [Tendbha.MYSQL_HA_ENABLE]: t('启用任务执行中'),
    [Tendbha.MYSQL_SINGLE_DESTROY]: t('删除任务执行中'),
    [Tendbha.MYSQL_SINGLE_DISABLE]: t('禁用任务执行中'),
    [Tendbha.MYSQL_SINGLE_ENABLE]: t('启用任务执行中'),
  };

  bk_biz_id: number;
  bk_biz_name: string;
  bk_cloud_id: number;
  bk_cloud_name: string;
  cluster_access_port: number;
  cluster_alias: string;
  cluster_entry: ClusterListEntry[];
  cluster_name: string;
  cluster_spec: ClusterListSpec;
  cluster_stats: Record<'used' | 'total' | 'in_use', number>;
  cluster_subzons: string[];
  cluster_time_zone: string;
  cluster_type: ClusterTypes;
  cluster_type_name: string;
  create_at: string;
  creator: string;
  db_module_id: number;
  db_module_name: string;
  disaster_tolerance_level: Affinity;
  dns_to_clb: boolean;
  id: number;
  immute_domain: string;
  major_version: string;
  master_domain: string;
  masters: ({ is_stand_by: boolean } & ClusterListNode)[];
  operations: ClusterListOperation[];
  permission: {
    access_entry_edit: boolean;
    mysql_add_clb: boolean;
    mysql_clb_bind_domain: boolean;
    mysql_destroy: boolean;
    mysql_dump_data: boolean;
    mysql_edit: boolean;
    mysql_enable_disable: boolean;
    mysql_view: boolean;
    mysql_webconsole: boolean;
    tbinlogdumper_install: boolean;
  };
  phase: string;
  phase_name: string;
  proxies: ClusterListNode[];
  region: string;
  slave_domain: string;
  slaves: ({ is_stand_by: boolean } & ClusterListNode)[];
  status: string;
  update_at: string;
  updater: string;

  constructor(payload = {} as Tendbha) {
    super(payload);
    this.bk_biz_id = payload.bk_biz_id || 0;
    this.bk_biz_name = payload.bk_biz_name || '';
    this.bk_cloud_id = payload.bk_cloud_id || 0;
    this.bk_cloud_name = payload.bk_cloud_name || '';
    this.cluster_subzons = payload.cluster_subzons || [];
    this.cluster_access_port = payload.cluster_access_port;
    this.cluster_alias = payload.cluster_alias;
    this.cluster_entry = payload.cluster_entry || [];
    this.cluster_name = payload.cluster_name || '';
    this.cluster_spec = payload.cluster_spec || {};
    this.cluster_stats = payload.cluster_stats || {};
    this.cluster_type = payload.cluster_type || '';
    this.cluster_type_name = payload.cluster_type_name || '';
    this.cluster_time_zone = payload.cluster_time_zone || '';
    this.create_at = payload.create_at || '';
    this.creator = payload.creator || '';
    this.db_module_name = payload.db_module_name || '';
    this.db_module_id = payload.db_module_id || 0;
    this.disaster_tolerance_level = payload.disaster_tolerance_level;
    this.dns_to_clb = payload.dns_to_clb;
    this.id = payload.id || 0;
    this.immute_domain = payload.immute_domain || '';
    this.master_domain = payload.master_domain || '';
    this.major_version = payload.major_version || '';
    this.masters = payload.masters || [];
    this.operations = payload.operations || [];
    this.permission = payload.permission || {};
    this.phase = payload.phase || '';
    this.phase_name = payload.phase_name || '';
    this.proxies = payload.proxies || [];
    this.region = payload.region || '';
    this.slave_domain = payload.slave_domain || '';
    this.slaves = payload.slaves || [];
    this.status = payload.status || '';
    this.update_at = payload.update_at;
    this.updater = payload.updater;
  }

  get allInstanceList() {
    return [...this.masters, ...this.proxies, ...this.slaves];
  }

  get allIPList() {
    return uniq(this.allInstanceList.map((item) => item.ip));
  }

  // 异常主机IP
  get allUnavailableIPList() {
    return uniq(
      this.allInstanceList.reduce(
        (pre, cur) => [...pre, ...(cur.status === 'unavailable' ? [cur.ip] : [])],
        [] as string[],
      ),
    );
  }

  get disasterToleranceLevelName() {
    return affinityMap[this.disaster_tolerance_level];
  }

  get isOnlineCLB() {
    return this.cluster_entry.some((item) => item.cluster_entry_type === 'clb');
  }

  get isStarting() {
    return Boolean(this.operations.find((item) => item.ticket_type === Tendbha.MYSQL_HA_ENABLE));
  }

  get masterDomainDisplayName() {
    const port = this.proxies[0]?.port;
    const displayName = port ? `${this.master_domain}:${port}` : this.master_domain;
    return displayName;
  }

  get operationDisabled() {
    // 集群异常不支持操作
    if (this.status === 'abnormal') {
      return true;
    }
    // 被禁用的集群不支持操作
    if (this.phase !== 'online') {
      return true;
    }
    // 各个操作互斥，有其他任务进行中禁用操作按钮
    if (this.operationTicketId) {
      return true;
    }
    return false;
  }

  // 操作中的状态
  get operationRunningStatus() {
    if (this.operations.length < 1) {
      return '';
    }
    const operation = this.runningOperation;
    if (!operation) {
      return '';
    }
    return operation.ticket_type;
  }

  // 操作中的状态描述文本
  get operationStatusText() {
    return Tendbha.operationTextMap[this.operationRunningStatus];
  }

  get operationTagTips() {
    return this.operations.reduce<{ icon: string; ticketId: number; tip: string }[]>((result, item) => {
      if (Tendbha.operationIconMap[item.ticket_type]) {
        result.push({
          icon: Tendbha.operationIconMap[item.ticket_type],
          ticketId: item.ticket_id,
          tip: Tendbha.operationTextMap[item.ticket_type],
        });
      }
      return result;
    }, []);
  }

  // 操作中的单据 ID
  get operationTicketId() {
    if (this.operations.length < 1) {
      return 0;
    }
    const operation = this.runningOperation;
    if (!operation) {
      return 0;
    }
    return operation.ticket_id;
  }

  get roleFailedInstanceInfo() {
    return {
      Master: ClusterBase.getRoleFaildInstanceList(this.masters),
      Slaves: ClusterBase.getRoleFaildInstanceList(this.slaves),
    };
  }

  get runningOperation() {
    const operateTicketTypes = Object.keys(Tendbha.operationTextMap);
    return this.operations.find((item) => operateTicketTypes.includes(item.ticket_type) && item.status === 'RUNNING');
  }

  get slaveEntryList() {
    const port = this.slaves[0]?.port;
    return this.cluster_entry
      .filter((item) => item.role === 'slave_entry')
      .map((item) => ({
        ...item,
        port,
      }));
  }

  get slaveList() {
    return this.slaves;
  }
}
