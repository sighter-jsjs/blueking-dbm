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

import axios, { type AxiosRequestConfig, type CancelTokenSource } from 'axios';
import Cookie from 'js-cookie';
import _ from 'lodash';
import qs from 'qs';

import { setCancelTokenSource } from '../index';
import requestMiddleware from '../middleware/request';
import responseMiddleware from '../middleware/response';

import Cache, { type CacheExpire, type CacheValue } from './cache';
import { paramsSerializer } from './utils';

const cacheHandler = new Cache();

export type Method = 'get' | 'delete' | 'post' | 'put' | 'download' | 'patch';
export interface Config {
  method: Method;
  params?: Record<string, any>;
  payload?: {
    cache?: string | number | boolean;
    catchError?: boolean;
    onUploadProgress?: (params: CancelTokenSource) => void;
    permission?: 'page' | 'dialog' | 'catch';
    timeout?: number;
  } & AxiosRequestConfig;
  url: string;
}

/* @ts-expect-error 插件类型问题 */
if (axios.interceptors.response.handlers.length < 1) {
  /* @ts-expect-error 插件类型问题 */
  requestMiddleware(axios.interceptors.request);
  responseMiddleware(axios.interceptors.response);
}

const { CancelToken } = axios;
const CSRF_TOKEN_KEY = 'dbm_csrftoken';

const CSRFToken = Cookie.get(CSRF_TOKEN_KEY);

axios.defaults.headers.common['X-Requested-With'] = 'XMLHttpRequest';
if (CSRFToken !== undefined) {
  axios.defaults.headers.common['X-CSRFToken'] = CSRFToken;
} else {
  console.warn('Can not find csrftoken in document.cookie');
}
const defaultConfig = {
  headers: {},
  paramsSerializer,
  timeout: 120000,
  withCredentials: true,
  xsrfCookieName: 'dbm_csrftoken',
  xsrfHeaderName: 'X-CSRFToken',
};

export default class Request {
  static bodyDataMethods = ['post', 'put', 'delete', 'patch'];
  static supporMethods = ['get', 'post', 'delete', 'put', 'patch'];
  static willCachedMethods = ['get'];

  cache: Cache;
  config: Config;

  constructor(config = {} as Config) {
    this.cache = cacheHandler;
    this.config = config;
  }

  get axiosConfig() {
    const config: Record<string, any> = Object.assign({}, defaultConfig, {
      baseURL: window.PROJECT_ENV.VITE_AJAX_URL_PREFIX,
      method: this.config.method,
      payload: this.config.payload || {},
      url: this.config.url,
    });

    if (this.config.params) {
      if (Request.bodyDataMethods.includes(this.config.method)) {
        config.data = this.config.params;
      } else {
        config.params = this.config.params;
      }
    }

    if (this.config.payload) {
      const configPayload = this.config.payload;
      Object.keys(configPayload).forEach((configExtend) => {
        config[configExtend] = configPayload[configExtend as keyof Config['payload']];
      });
    }

    return config;
  }

  get isCachedable() {
    if (!Request.willCachedMethods.includes(this.config.method)) {
      return false;
    }
    if (!this.config.payload || !_.has(this.config.payload, 'cache')) {
      return false;
    }
    return true;
  }

  get taskKey() {
    return `${this.config.method}_${this.config.url}_${JSON.stringify(this.config.params)}`;
  }

  checkCache() {
    return this.isCachedable && this.cache.has(this.taskKey);
  }

  deleteCache() {
    this.cache.delete(this.taskKey);
  }

  run() {
    if (this.checkCache()) {
      return this.cache.get(this.taskKey);
    }

    const source = CancelToken.source();
    setCancelTokenSource(source);

    const requestHandler = axios({
      ...this.axiosConfig,
      cancelToken: source.token,
      paramsSerializer(params) {
        return qs.stringify(params, { arrayFormat: 'repeat' });
      },
    }).then((data) => {
      this.setCache(requestHandler);
      return data.data;
    });
    this.setCache(requestHandler);
    return requestHandler;
  }

  setCache(data: CacheValue) {
    this.isCachedable && this.cache.set(this.taskKey, data, this.config.payload?.cache as CacheExpire);
  }
}
