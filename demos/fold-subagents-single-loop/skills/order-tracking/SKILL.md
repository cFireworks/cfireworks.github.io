---
name: order-tracking
description: 顾客问订单到哪了、哪天能到、运单走到哪一步时加载。覆盖查单和物流轨迹。
---

# 订单和物流

顾客要送达时间时，先调用 `lookup_order`。日期不在订单状态里。再用结果里的 `tracking_id` 调用 `track_shipment`，原样传入，不要改写。

对用户说出承运商、运输状态、预计送达日和最后一条轨迹。预计送达日只引用 `track_shipment` 返回的 `eta`。

`track_shipment` 若回答没有运单号，先把缺的字段补上再调，不要编一个日期。
