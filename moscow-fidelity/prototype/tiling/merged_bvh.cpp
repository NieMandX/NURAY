// Bounded-memory SAH accelerator for the exact packed geometry in a merged GLB.
// Output: reordered uint32 triangle indices, then 32-byte preorder BVH nodes.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <vector>
struct Bounds {
  float lo[3]={INFINITY,INFINITY,INFINITY},hi[3]={-INFINITY,-INFINITY,-INFINITY};
  void add(const Bounds& b){for(int a=0;a<3;a++){lo[a]=std::min(lo[a],b.lo[a]);hi[a]=std::max(hi[a],b.hi[a]);}}
  double area() const {double x=std::max(0.f,hi[0]-lo[0]),y=std::max(0.f,hi[1]-lo[1]),z=std::max(0.f,hi[2]-lo[2]);return x*y+y*z+z*x;}
};
struct Node {float lo[3];uint32_t first;float hi[3];uint32_t count;};
static_assert(sizeof(Node)==32);
struct Builder {
  std::vector<Bounds> bounds;std::vector<uint32_t> order;std::vector<Node> nodes;unsigned depth=0;
  float center(uint32_t i,int a) const {return .5f*(bounds[i].lo[a]+bounds[i].hi[a]);}
  void build(uint32_t start,uint32_t end,unsigned level=0){
    auto node=nodes.size();nodes.emplace_back();depth=std::max(depth,level);
    Bounds box,centers;
    for(auto i=start;i<end;i++){box.add(bounds[order[i]]);for(int a=0;a<3;a++){auto c=center(order[i],a);centers.lo[a]=std::min(centers.lo[a],c);centers.hi[a]=std::max(centers.hi[a],c);}}
    std::copy(box.lo,box.lo+3,nodes[node].lo);std::copy(box.hi,box.hi+3,nodes[node].hi);
    if(end-start<=8){nodes[node].first=start;nodes[node].count=end-start;return;}
    constexpr int B=16;int axis=-1,split=0;double best=INFINITY;float chosenScale=0;
    if(level<48)for(int a=0;a<3;a++){
      float extent=centers.hi[a]-centers.lo[a];if(extent<=1e-9f)continue;
      float scale=B/extent;std::array<Bounds,B> boxes;std::array<uint32_t,B> counts{};
      auto bin=[&](uint32_t id){return std::clamp(int((center(id,a)-centers.lo[a])*scale),0,B-1);};
      for(auto i=start;i<end;i++){int j=bin(order[i]);boxes[j].add(bounds[order[i]]);counts[j]++;}
      std::array<double,B> prefix{};std::array<uint32_t,B> nums{};Bounds left;uint32_t n=0;
      for(int j=0;j<B;j++){left.add(boxes[j]);n+=counts[j];prefix[j]=n?left.area()*n:0;nums[j]=n;}
      Bounds right;n=0;
      for(int j=B-1;j>0;j--){right.add(boxes[j]);n+=counts[j];if(!n||!nums[j-1])continue;double cost=prefix[j-1]+right.area()*n;if(cost<best){best=cost;axis=a;split=j;chosenScale=scale;}}
    }
    uint32_t middle=(start+end)/2;
    if(axis>=0){auto p=std::partition(order.begin()+start,order.begin()+end,[&](uint32_t id){return int((center(id,axis)-centers.lo[axis])*chosenScale)<split;});middle=p-order.begin();}
    if(middle==start||middle==end)middle=(start+end)/2;
    build(start,middle,level+1);build(middle,end,level+1);nodes[node].first=nodes.size();nodes[node].count=0;
  }
  // Validate traversal escape indices, complete leaf coverage and containment.
  uint32_t validate(uint32_t node,uint32_t& cursor) const {
    if(node>=nodes.size())throw std::runtime_error("BVH node out of range");const auto& n=nodes[node];
    auto contains=[&](const float* lo,const float* hi){for(int a=0;a<3;a++)if(lo[a]<n.lo[a]||hi[a]>n.hi[a])throw std::runtime_error("BVH bounds do not contain child");};
    if(n.count){if(n.first!=cursor||n.count>8)throw std::runtime_error("Invalid leaf range");for(uint32_t i=0;i<n.count;i++){const auto& b=bounds[order[cursor++]];contains(b.lo,b.hi);}return node+1;}
    auto right=validate(node+1,cursor),escape=validate(right,cursor);contains(nodes[node+1].lo,nodes[node+1].hi);contains(nodes[right].lo,nodes[right].hi);
    if(n.first!=escape)throw std::runtime_error("Invalid escape index");return escape;
  }
};
std::vector<uint32_t> read(std::ifstream& f,uint64_t offset,uint64_t bytes){
  if(bytes%4)throw std::runtime_error("Unaligned geometry");std::vector<uint32_t> out(bytes/4);f.seekg(offset);f.read(reinterpret_cast<char*>(out.data()),bytes);if(!f)throw std::runtime_error("Truncated GLB");return out;
}
int main(int argc,char** argv){try{
  if(argc!=7)throw std::runtime_error("usage: merged_bvh GLB vertexOffset vertexBytes indexOffset indexBytes output");
  std::ifstream input(argv[1],std::ios::binary);auto vertices=read(input,std::stoull(argv[2]),std::stoull(argv[3]));auto indices=read(input,std::stoull(argv[4]),std::stoull(argv[5]));
  if(vertices.size()%8||indices.size()%3||indices.empty())throw std::runtime_error("Invalid mesh layout");
  Builder b;auto count=indices.size()/3;b.bounds.resize(count);b.order.resize(count);std::iota(b.order.begin(),b.order.end(),0);b.nodes.reserve(count/2);
  Bounds local;
  for(size_t v=0;v<vertices.size();v+=8)for(int a=0;a<3;a++){float p;std::memcpy(&p,&vertices[v+a],4);if(!std::isfinite(p))throw std::runtime_error("Nonfinite vertex");local.lo[a]=std::min(local.lo[a],p);local.hi[a]=std::max(local.hi[a],p);}
  for(size_t t=0;t<count;t++)for(int c=0;c<3;c++){auto v=uint64_t(indices[t*3+c])*8;if(v+7>=vertices.size())throw std::runtime_error("Invalid vertex index");for(int a=0;a<3;a++){float p;std::memcpy(&p,&vertices[v+a],4);b.bounds[t].lo[a]=std::min(b.bounds[t].lo[a],std::nextafter(p-.00002f,-INFINITY));b.bounds[t].hi[a]=std::max(b.bounds[t].hi[a],std::nextafter(p+.00002f,INFINITY));}}
  b.build(0,count);uint32_t cursor=0;if(b.validate(0,cursor)!=b.nodes.size()||cursor!=count)throw std::runtime_error("Incomplete BVH");
  std::vector<uint32_t> sorted(indices.size());for(size_t i=0;i<count;i++)std::copy_n(indices.data()+b.order[i]*3,3,sorted.data()+i*3);
  std::ofstream output(argv[6],std::ios::binary);output.write(reinterpret_cast<char*>(sorted.data()),sorted.size()*4);output.write(reinterpret_cast<char*>(b.nodes.data()),b.nodes.size()*32);if(!output)throw std::runtime_error("Cannot write BVH");
  std::cout.precision(10);std::cout<<"{\"nodeCount\":"<<b.nodes.size()<<",\"maxDepth\":"<<b.depth<<",\"triangles\":"<<count<<",\"bounds\":{\"min\":["<<local.lo[0]<<","<<local.lo[1]<<","<<local.lo[2]<<"],\"max\":["<<local.hi[0]<<","<<local.hi[1]<<","<<local.hi[2]<<"]}}\n";
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}}
