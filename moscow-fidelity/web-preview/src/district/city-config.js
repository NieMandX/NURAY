import {modelBaseUrl} from '../../model-config.js?v=moscow-defaults-1';
export const cityBase=new URL(modelBaseUrl,new URL('../../',import.meta.url));
export const cityManifest=new URL('scene.json',cityBase);
