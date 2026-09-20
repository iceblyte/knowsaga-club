/// <reference types="@tarojs/taro" />

/**
 * 构建期注入的应用版本号，来自 `frontend/package.json` 的 `version`
 * （定义见 `config/index.ts` 的 `defineConstants`）。
 *
 * 它是 DefinePlugin 的**文本替换**，不是一个真正的全局变量 ——
 * 所以只能在源码里字面写 `APP_VERSION`，不能 `globalThis.APP_VERSION`
 * 或解构到别的对象上。
 */
declare const APP_VERSION: string

declare module '*.png';
declare module '*.gif';
declare module '*.jpg';
declare module '*.jpeg';
declare module '*.svg';
declare module '*.css';
declare module '*.less';
declare module '*.scss';
declare module '*.sass';
declare module '*.styl';

declare namespace NodeJS {
  interface ProcessEnv {
    /** NODE 内置环境变量, 会影响到最终构建生成产物 */
    NODE_ENV: 'development' | 'production',
    /** 当前构建的平台 */
    TARO_ENV: 'weapp' | 'swan' | 'alipay' | 'h5' | 'rn' | 'tt' | 'qq' | 'jd' | 'harmony' | 'jdrn'
    /**
     * 当前构建的小程序 appid
     * @description 若不同环境有不同的小程序，可通过在 env 文件中配置环境变量`TARO_APP_ID`来方便快速切换 appid， 而不必手动去修改 dist/project.config.json 文件
     * @see https://taro-docs.jd.com/docs/next/env-mode-config#特殊环境变量-taro_app_id
     */
    TARO_APP_ID: string
    /**
     * 后端地址，在 `.env.<mode>` 中定义（见 src/constants/api.ts）。
     * 写成必填是为了让「忘了在 env 文件里定义」这件事在类型层面就能被注意到 ——
     * 未定义的键不会被 DefinePlugin 替换，会在运行时炸掉。
     */
    TARO_APP_API_BASE_URL: string
  }
}


