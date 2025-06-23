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
import { uniq } from 'lodash';

import type { ClusterListEntry, ClusterListNode, ClusterListOperation, ClusterListSpec } from '@services/types';

import { Affinity, affinityMap, ClusterTypes } from '@common/const';

import { t } from '@locales/index';

import ClusterBase from '../_clusterBase';

export default class Redis extends ClusterBase {
  static REDIS_DESTROY = 'REDIS_DESTROY';
  static REDIS_INSTANCE_CLOSE = 'REDIS_INSTANCE_CLOSE';
  static REDIS_INSTANCE_DESTROY = 'REDIS_INSTANCE_DESTROY';
  static REDIS_INSTANCE_OPEN = 'REDIS_INSTANCE_OPEN';
  static REDIS_PROXY_CLOSE = 'REDIS_PROXY_CLOSE';
  static REDIS_PROXY_OPEN = 'REDIS_PROXY_OPEN';

  static operationIconMap = {
    [Redis.REDIS_DESTROY]: t('删除中'),
    [Redis.REDIS_INSTANCE_CLOSE]: t('禁用中'),
    [Redis.REDIS_INSTANCE_DESTROY]: t('删除中'),
    [Redis.REDIS_INSTANCE_OPEN]: t('启用中'),
    [Redis.REDIS_PROXY_CLOSE]: t('禁用中'),
    [Redis.REDIS_PROXY_OPEN]: t('启用中'),
  };

  static operationTextMap = {
    [Redis.REDIS_DESTROY]: t('删除任务执行中'),
    [Redis.REDIS_INSTANCE_CLOSE]: t('禁用任务执行中'),
    [Redis.REDIS_INSTANCE_DESTROY]: t('删除任务执行中'),
    [Redis.REDIS_INSTANCE_OPEN]: t('启用任务执行中'),
    [Redis.REDIS_PROXY_CLOSE]: t('禁用任务执行中'),
    [Redis.REDIS_PROXY_OPEN]: t('启用任务执行中'),
  };

  bk_biz_id: number;
  bk_biz_name: string;
  bk_cloud_id: number;
  bk_cloud_name: string;
  city: string;
  cluster_access_port: number;
  cluster_alias: string;
  cluster_capacity: number;
  cluster_entry: ClusterListEntry[];
  cluster_name: string;
  cluster_shard_num: number;
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
  machine_pair_cnt: number;
  major_version: string;
  master_domain: string;
  module_names: string[];
  operations: ClusterListOperation[];
  permission: {
    access_entry_edit: boolean;
    redis_access_entry_view: boolean;
    redis_backup: boolean;
    redis_destroy: boolean;
    redis_edit: boolean;
    redis_keys_delete: boolean;
    redis_keys_extract: boolean;
    redis_open_close: boolean;
    redis_plugin_create_clb: boolean;
    redis_plugin_create_polaris: boolean;
    redis_plugin_dns_bind_clb: boolean;
    redis_purge: boolean;
    redis_source_access_view: boolean;
    redis_view: boolean;
    redis_webconsole: boolean;
  };
  phase: string;
  phase_name: string;
  proxy: ClusterListNode[];
  redis_master: ({ seg_range: string } & ClusterListNode)[];
  redis_slave: ({ seg_range: string } & ClusterListNode)[];
  region: string;
  slave_domain: string;
  status: string;
  update_at: string;
  updater: string;

  constructor(payload = {} as Redis) {
    super(payload);
    this.bk_biz_id = payload.bk_biz_id;
    this.bk_biz_name = payload.bk_biz_name;
    this.bk_cloud_id = payload.bk_cloud_id;
    this.city = payload.city;
    this.bk_cloud_name = payload.bk_cloud_name;
    this.cluster_subzons = payload.cluster_subzons || [];
    this.cluster_access_port = payload.cluster_access_port;
    this.cluster_alias = payload.cluster_alias;
    this.cluster_capacity = payload.cluster_capacity;
    this.cluster_entry = payload.cluster_entry || [];
    this.cluster_name = payload.cluster_name;
    this.cluster_shard_num = payload.cluster_shard_num;
    this.cluster_spec = payload.cluster_spec || {};
    this.cluster_stats = payload.cluster_stats || {};
    this.cluster_time_zone = payload.cluster_time_zone;
    this.cluster_type = payload.cluster_type;
    this.cluster_type_name = payload.cluster_type_name;
    this.create_at = payload.create_at;
    this.creator = payload.creator;
    this.db_module_id = payload.db_module_id;
    this.db_module_name = payload.db_module_name;
    this.disaster_tolerance_level = payload.disaster_tolerance_level || '';
    this.dns_to_clb = payload.dns_to_clb;
    this.id = payload.id;
    this.machine_pair_cnt = payload.machine_pair_cnt;
    this.major_version = payload.major_version;
    this.master_domain = payload.master_domain;
    this.module_names = payload.module_names || [];
    this.operations = payload.operations || [];
    this.permission = payload.permission || {};
    this.phase = payload.phase;
    this.phase_name = payload.phase_name;
    this.proxy = payload.proxy || [];
    this.redis_master = payload.redis_master || [];
    this.redis_slave = payload.redis_slave || [];
    this.region = payload.region;
    this.slave_domain = payload.slave_domain;
    this.status = payload.status;
    this.update_at = payload.update_at;
    this.updater = payload.updater;
  }

  get allInstanceList() {
    return [...this.proxy, ...this.redis_master, ...this.redis_slave];
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

  get count() {
    return this.storageCount + this.proxyCount;
  }

  get disasterToleranceLevelName() {
    return affinityMap[this.disaster_tolerance_level];
  }

  get isOnlineCLB() {
    return this.cluster_entry.some((item) => item.cluster_entry_type === 'clb');
  }

  get isOnlinePolaris() {
    return this.cluster_entry.some((item) => item.cluster_entry_type === 'polaris');
  }

  get isSlaveNormal() {
    return this.redis_slave.every((item) => item.status === 'running');
  }

  get isStarting() {
    return Boolean(this.operations.find((item) => item.ticket_type === Redis.REDIS_PROXY_OPEN));
  }

  get masterDomainDisplayName() {
    const port = this.cluster_type === ClusterTypes.REDIS_INSTANCE ? this.redis_master[0]?.port : this.proxy[0]?.port;
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
    return Redis.operationTextMap[this.operationRunningStatus];
  }

  get operationTagTips() {
    return this.operations.map((item) => ({
      icon: Redis.operationIconMap[item.ticket_type],
      ticketId: item.ticket_id,
      tip: Redis.operationTextMap[item.ticket_type],
    }));
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

  get proxyCount() {
    const len = this.proxy.length;
    if (len <= 1) {
      return len;
    }
    return new Set(this.proxy.map((item) => item.ip)).size;
  }

  get redisInstanceMasterDomainDisplayName() {
    const port = this.cluster_access_port;
    const displayName = port ? `${this.master_domain}:${port}` : this.master_domain;
    return displayName;
  }

  get redisMasterCount() {
    const len = this.redis_master.length;
    if (len <= 1) {
      return len;
    }
    return new Set(this.redis_master.map((item) => item.ip)).size;
  }

  get redisMasterFaultNum() {
    const ips = this.redis_master.reduce((result, item) => {
      if (item.status !== 'running') {
        result.push(item.ip);
      }
      return result;
    }, [] as string[]);
    return new Set(ips).size;
  }

  get redisSlaveCount() {
    const len = this.redis_slave.length;
    if (len <= 1) {
      return len;
    }
    return new Set(this.redis_slave.map((item) => item.ip)).size;
  }

  get redisSlaveFaults() {
    const ips = this.redis_slave.reduce((result, item) => {
      if (item.status !== 'running') {
        result.push(item.ip);
      }
      return result;
    }, [] as string[]);
    return new Set(ips).size;
  }

  get roleFailedInstanceInfo() {
    return {
      Master: ClusterBase.getRoleFaildInstanceList(this.redis_master),
      Slave: ClusterBase.getRoleFaildInstanceList(this.redis_slave),
    };
  }

  get runningOperation() {
    const operateTicketTypes = Object.keys(Redis.operationTextMap);
    return this.operations.find((item) => operateTicketTypes.includes(item.ticket_type) && item.status === 'RUNNING');
  }

  get slaveEntryList() {
    const port = this.redis_slave[0]?.port;
    return this.cluster_entry
      .filter((item) => item.role === 'slave_entry')
      .map((item) => ({
        ...item,
        port,
      }));
  }

  get slaveList() {
    return this.redis_slave;
  }

  get storageCount() {
    return this.redisMasterCount + this.redisSlaveCount;
  }
}
