#include <stdio.h>
#include "ArHosekSkyModel.h"
extern double arhosekskymodel_solar_radiance_internal2(ArHosekSkyModelState*,double,double,double);
int main(){double t[]={1,3.7,10},a[]={0,.23,1},e[]={0,.31,1.5707963267948966};
for(int i=0;i<3;i++)for(int j=0;j<3;j++)for(int k=0;k<3;k++){
 ArHosekSkyModelState *s=arhosek_rgb_skymodelstate_alloc_init(t[i],a[j],e[k]);
 ArHosekSkyModelState *q=arhosekskymodelstate_alloc_init(e[k],t[i],a[j]);
 printf("[%g,%g,%.17g",t[i],a[j],e[k]);
 for(int c=0;c<3;c++)printf(",%.17g",arhosek_tristim_skymodel_radiance(s,.71,1.12,c));
 for(int w=400;w<=720;w+=80)printf(",%.17g",arhosekskymodel_solar_radiance_internal2(q,w,e[k],.002));
 puts("]");arhosekskymodelstate_free(s);arhosekskymodelstate_free(q);
}}
