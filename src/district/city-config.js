import {modelBaseUrl} from '../../model-config.js?v=fidelity-2';
export const cityBase=new URL(modelBaseUrl,new URL('../../',import.meta.url));
export const cityManifest=new URL('scene.json',cityBase);
