# Authoritative Place ID Lifecycle & Knowledge Graph Status Audit

**Audit Date**: 2026-09-08T14:37:38Z  
**Total Catalog Places**: 11,221  
**Places Visited in Timeline**: 7,718  

---

## 1. Lifecycle Status Distribution

| Lifecycle Status | Verification Status | Count | % of Catalog | Description |
| :--- | :--- | :---: | :---: | :--- |
| **OPERATIONAL** | `VERIFIED_GOOGLE_GRAPH` | 8,838 | 78.8% | Active, resolvable commercial and public venues in Google Maps |
| **CITIBIKE_STATION** | `CITIBIKE_NETWORK` | 2,062 | 18.4% | Micro-mobility docking network stations |
| **DELETED_FROM_MAPS** | `DELETED_FID_CONFIRMED` | 192 | 1.7% | **Places where Google deleted the FID from its Knowledge Graph** |
| **PLAZES_CHECKIN** | `PLAZES_ARCHIVE` | 75 | 0.7% | Legacy historical check-ins from Plazes archives |
| **CUSTOM_RESIDENCE** | `CUSTOM_RESIDENCE` | 51 | 0.5% | Verified personal residences, schools, and private bases |
| **CLOSED_PERMANENTLY** | `VERIFIED_CLOSED` | 3 | 0.0% | Confirmed permanently closed historical venues (e.g., wd-50, Standard Toykraft) |

---

## 2. Deleted Feature IDs (FIDs) – The Root Cause of Missing POIs

When Google Maps retired these Feature IDs instead of marking them `PERMANENTLY_CLOSED`, the Timeline backend deleted the corresponding visits, creating unrecorded gaps and long moving intervals. These entities are preserved in our catalog with their authoritative names and addresses:

| Venue Name | Address | Place ID | S2 Cell / Fingerprint | In Timeline? |
| :--- | :--- | :--- | :--- | :---: |
| **OCF Coffee House** | 2100 Fairmount Ave, Philadelphia, Pennsylvania 19130, United States | `ChIJC6gyMsnHxokRQko7JhyoTv4` | `0x89c6c7c93232a80b:0xfe4ea81c263b4a42` | Catalog |
| **MeMe Antenna** | 218 Bedford Avenue, Brooklyn, New York 11249-3234, United States | `ChIJx8E1BF5ZwokRbvz54rhXpfw` | `0x89c2595e0435c1c7:0xfca557b8e2f9fc6e` | Catalog |
| **The Cliffs at DUMBO** | 99 Plymouth Street, Brooklyn, New York 11201, United States | `ChIJGw950zNawokRBX_7jOyaUH4` | `0x89c25a33d3790f1b:0x7e509aec8cfb7f05` | Catalog |
| **1 Main St** | 1 Main St, Ossining, NY 10562, USA | `ChIJvUo0NcHAwokRaW4aUIxNWEM` | `0x89c2c0c135344abd:0x43584d8c501a6e69` | Yes |
| **Kostume Kult** | Kostume Kult, 333 Esplanade, Nevada 89412, United States | `ChIJdZ79m8W5n4ARPrdrrIWRlOY` | `0x809fb9c59bfd9e75:0xe6949185ac6bb73e` | Catalog |
| **Azabu Juban Noryo Matsuri** | 日本、〒106-0045 東京都港区麻布十番２丁目３−１０ | `ChIJmyLe16GLGGAR8gMkrsdneJI` | `0x60188ba1d7de229b:0x927867c7ae2403f2` | Yes |
| **Saved Location** | N/A | `ChIJtwOCu6GLGGARAAAAAAAAAAA` | `N/A` | Yes |
| **Saved Location** | N/A | `ChIJxeVX91P_0YURAAAAAAAAAAA` | `N/A` | Yes |
| **El Taco Poblano** | C. 16 de Septiembre 906, col centro, 72000 Heroica Puebla de Zaragoza, Pue., México | `ChIJ8aa3TN3Az4URLwQ-AZyx8RA` | `0x85cfc0dd4cb7a6f1:0x10f1b19c013e042f` | Yes |
| **204 E 13th St** | 204 E 13th St, New York, 10003-5684, United States | `ChIJq2Gt6p5ZwokRAsAatkpvsbQ` | `0x89c2599eeaad61ab:0xb4b16f4ab61ac002` | Yes |
| **Google Building 8510** | 4, 85 10th Avenue, New York, 10011, United States | `ChIJCZgntsBZwokRTNb-R11f-PA` | `0x89c259c0b6279809:0xf0f85f5d47fed64c` | Catalog |
| **RN-5** | RN-5, San Salvador, El Salvador | `ChIJR2HSz3u2fI8RYuSWq4EHTpA` | `0x8f7cb67bcfd26147:0x904e0781ab96e462` | Catalog |
| **Orchard Plaza** | 2295 S Virginia St, Reno, NV 89502, USA | `ChIJ79dKP5BAmYARS6wNNiBZiKM` | `0x809940903f4ad7ef:0xa3885920360dac4b` | Catalog |
| **Mary Boone Gallery** | 541 W 24th St, New York, NY 10011, USA | `ChIJCewFjrdZwokRsvKj2MTEy8U` | `0x89c259b78e05ec09:0xc5cbc4c4d8a3f2b2` | Yes |
| **Kings Cross** | London Borough of Camden, London, UK | `ChIJzU08xxAbdkgRuWtd0P4Rb2E` | `0x48761b10c73c4dcd:0x616f11fed05d6bb9` | Catalog |
| **Saved Location** | N/A | `ChIJM-Kmy-zHh0gRAAAAAAAAAAA` | `N/A` | Yes |
| **Saved Location** | Hornbachstrasse 74, Kreis 8, 8008 Zürich, Suisse | `ChIJ742IvEinmkcRrSDaTbaiKwo` | `0x479aa748bc888def:0xa2ba2b64dda20ad` | Yes |
| **Staumauer Gigerwald** | Gigerwald, 7315 Pfäfers, Schweiz | `ChIJq7F2lPPPhEcR5NQWhJ28AK4` | `0x4784cff39476b1ab:0xae00bc9d8416d4e4` | Yes |
| **FIG & OLIVE | Meatpacking** | 420 W 13th St, New York, NY 10014, USA | `ChIJ07ujcMBZwokRkYedKAwgegg` | `0x89c259c070a3bbd3:0x87a200c289d8791` | Yes |
| **Plaza San Francisco** | 0°13'14. 78°30'54., 8, Quito, Pichincha, Ecuador | `ChIJTXN0WcKZ1ZERBvpiwDZTrBE` | `0x91d599c25974734d:0x11ac5336c062fa06` | Yes |
| **Finnerty's** | 221 2nd Ave, New York, NY 10003, USA | `ChIJxfoyXJ5ZwokRg-rmPb8_X5E` | `0x89c2599e5c32fac5:0x915f3fbf3de6ea83` | Catalog |
| **Sweet Home Cafe** | 2334 S King St, Honolulu, HI 96826, USA | `ChIJOb7fnpFtAHwRhbeZIRHnU9U` | `0x7c006d919edfbe39:0xd553e7112199b785` | Yes |
| **Oasis Bagels Cafe Deli & Grill** | 95-11 Rockaway Beach Blvd, Rockaway Beach, NY 11693, USA | `ChIJa_9crXNpwokRHsSc_ZhGZWg` | `0x89c26973ad5cff6b:0x68654698fd9cc41e` | Yes |
| **Red Hook Food Vendors Marketplace** | 160 Bay St, Brooklyn, NY 11231, USA | `ChIJL4SCrvNawokRMm34pefbMRU` | `0x89c25af3ae82842f:0x1531dbe7a5f86d32` | Yes |
| **Bergbahnstation Furi** | Furi, 3920 Zermatt, Schweiz | `ChIJw7S52qM1j0cRdJAxGzTcTjU` | `0x478f35a3dab9b4c3:0x354edc341b319074` | Catalog |
| **645 E 11th St #1F** | 645 E 11th St #1F, New York, NY 10009, USA | `ChIJv5APLHdZwokRp8U-7sVcCCU` | `0x89c259772c0f90bf:0x25085cc5ee3ec5a7` | Catalog |
| **The Cannibal Beer & Butcher** | 113 East 29th Street, New York, 10016-8027, United States | `ChIJ986BIQhZwokRWx8t-bv53Xk` | `0x89c259082181cef7:0x79ddf9bbf92d1f5b` | Yes |
| **1119 FDR Dr** | 1119 FDR Dr, New York, NY 10009, USA | `ChIJOSM9BetZwokRk5w41iwqR7M` | `0x89c259eb053d2339:0xb3472a2cd6389c93` | Catalog |
| **La Terrazza Del Gianicolo** | Piazzale Giuseppe Garibaldi, 00165 Roma RM, Italia | `ChIJpc7XH0BgLxMRiNHIRl4mKAc` | `0x132f60401fd7cea5:0x728265e46c8d188` | Catalog |
| **Blaze** | 5 Bay Vw Lndg, Camden, ME 04843, USA | `ChIJYaakGwzXrUwR3SFyIkC4U24` | `0x4cadd70c1ba4a661:0x6e53b840227221dd` | Catalog |
| **Granny Za's Weed Marijuana Dispensary** | Front Room, 81 Rivington St, New York, NY 10002, USA | `ChIJZdb7hklZwokRl15Dvyn5IK0` | `0x89c2594986fbd665:0xad20f929bf435e97` | Yes |
| **623 E 6th St** | 623 E 6th St, New York, NY 10009, USA | `ChIJKRdpNHhZwokRr3DhXXHYc4E` | `0x89c2597834691729:0x8173d8715de170af` | Yes |
| **Baohaus** | 238 E. 14th St, New York, 10003, United States | `ChIJx8sGD4FZwokRy6hAmRfzwqg` | `0x89c259810f06cbc7:0xa8c2f3179940a8cb` | Catalog |
| **The Whiskey Ward** | 121 Essex St, New York, NY 10002, USA | `ChIJbxbXO4FZwokRH8kYhkXOcE4` | `0x89c259813bd7166f:0x4e70ce458618c91f` | Catalog |
| **Saved Location** | N/A | `ChIJp5paBStFf7wRAAAAAAAAAAA` | `N/A` | Yes |
| **Saved Location** | N/A | `ChIJP0tAzW59f7wRAAAAAAAAAAA` | `N/A` | Yes |
| **Maison Blunt** | Gasometerstrasse 5, 8005 Zürich, Schweiz | `ChIJOfWZlBMKkEcRg-eYr3Ge3Ig` | `0x47900a139499f539:0x88dc9e71af98e783` | Catalog |
| **Bolton Boat Rentals and Tours** | 5024 Lake Shore Dr, Bolton Landing, NY 12814, USA | `ChIJEzcwiCnm34kR0fvofJWzZXs` | `0x89dfe62988303713:0x7b65b3957ce8fbd1` | Yes |
| **Saved Location** | N/A | `ChIJP8rmVIJZwokRAAAAAAAAAAA` | `N/A` | Yes |
| **Du's Donuts & Coffee** | 107 N 12th St, Brooklyn, NY 11249, USA | `ChIJkZ4gzkJZwokRlN9IIaPZ9Mw` | `0x89c25942ce209e91:0xccf4d9a32148df94` | Catalog |
| **The Harrison** | 355 Greenwich St, New York, NY 10013, USA | `ChIJNS8sJR5awokRCAK-RuP6co0` | `0x89c25a1e252c2f35:0x8d72fae346be0208` | Catalog |
| **Brunch Box** | 620 SW 9th Ave., Portland, OR 97205, USA | `ChIJ5V6vJgQKlVQR6yHjUUBnbck` | `0x54950a0426af5ee5:0xc96d674051e321eb` | Catalog |
| **63 Lafayette Avenue** | 63 Lafayette Avenue, Staten Island, New York 10301-1216, United States | `ChIJX36lRCNOwokRo9ZXFCDrqnU` | `0x89c24e2344a57e5f:0x75aaeb201457d6a3` | Catalog |
| **Bien Mur Travel Center Smoke Shop** | 100 Bien Mur Dr N E, Albuquerque, NM 87113, USA | `ChIJ8f6DbId2IocRWIPnqSl3hRc` | `0x872276876c83fef1:0x17857729a9e78358` | Catalog |
| **Pacific Grill** | 800 N Date St, Truth or Consequences, NM 87901, USA | `ChIJ3a8l4uaC34YR5gF4YZ_vjyc` | `0x86df82e6e225afdd:0x278fef9f617801e6` | Yes |
| **That Witch Ales You** | 116 Madison St, New York, NY 10002, USA | `ChIJk6Og40BbwokRNZMkXBAdGGI` | `0x89c25b40e3a0a393:0x62181d105c249335` | Yes |
| **Iron Hill** | 30 E State St, Media, PA 19063, USA | `ChIJFQZq_AfpxokRkW64NToJgH8` | `0x89c6e907fc6a0615:0x7f80093a35b86e91` | Yes |
| **Saved Location** | Yawning Cobra, 356, Bowery, NoHo, Manhattan, New York County, New York, 10012, United States | `ChIJa4GPKptZwokRAAAAAAAAAAA` | `N/A` | Yes |
| **Mickey Zane Place** | 635 Healdsburg Ave, Santa Rosa, CA 95401, USA | `ChIJdSReePhHhIARabmiBlaKBNk` | `0x808447f8785e2475:0xd9048a5606a2b969` | Catalog |
| **Amazing Parties** | 20 Hampton Rd # A, Southampton, NY 11968-4959, United States | `ChIJ0dyAlNyU6IkR2k1Xw14bg18` | `0x89e894dc9480dcd1:0x5f831b5ec3574dda` | Yes |
| **Saved Location** | N/A | `ChIJEbn-paeOGGARAAAAAAAAAAA` | `N/A` | Yes |
| **Bike Man Sale Repair Accessories Ebike/bicycle** | 174 Delancey Street, New York, 10002, United States | `ChIJ23eKToBZwokRmkJjc9xKnBQ` | `0x89c259804e8a77db:0x149c4adc7363429a` | Yes |
| **The Well** | 272 Meserole St, Brooklyn, NY 11206, USA | `ChIJI9Ry3f9bwokRiLLbdTv8IPw` | `0x89c25bffdd72d423:0xfc20fc3b75dbb288` | Catalog |
| **The Heidelberg Project** | 42 Watson Street, Detroit, Michigan 48201, United States | `ChIJ7xWsM8rSJIgRb3JltkCYsPA` | `0x8824d2ca33ac15ef:0xf0b09840b665726f` | Yes |
| **High Line 30th St Elevator Access** | N/A | `ChIJabOADK9ZwokRhR157dMns_o` | `0x89c259af0c80b369:0xfab327d3ed791d85` | Catalog |
| **The Finch** | 212 Greene Ave, Brooklyn, NY 11238, USA | `ChIJyQdqNrxbwokRk6a16M-ITzI` | `0x89c25bbc366a07c9:0x324f88cfe8b5a693` | Catalog |
| **Arts and Crafts Beer Parlor** | 26 W 8th St, New York, NY 10011, USA | `ChIJp8_A1ZZZwokRC9QaO2MSZEE` | `0x89c25996d5c0cfa7:0x416412633b1ad40b` | Yes |
| **Foragers Table** | 300 West 22nd Street, New York, 10011, United States | `ChIJcw0T1btZwokR7r6Jhz_meu4` | `0x89c259bbd5130d73:0xee7ae63f8789beee` | Catalog |
| **95-26 Queens Blvd** | 95-26 Queens Blvd, Flushing, NY 11374, USA | `ChIJJzaIljBewokRZrzqNujHsoA` | `0x89c25e3096883627:0x80b2c7e836eabc66` | Yes |
| **Do More Now** | &, 7:30 & Ballyhoo, Nevada, United States | `ChIJ9RUwQyW4n4ARFNGD05W9IpA` | `0x809fb825433015f5:0x9022bd95d383d114` | Yes |

*(Showing first 60 of 192 confirmed deleted FIDs)*

---

## 3. Verified Permanently Closed Historical Venues

| Venue Name | Address | Place ID | Closure Source |
| :--- | :--- | :--- | :--- |
| **Tink's** | 102 E 7th St, New York, NY 10009, USA | `ChIJ9cyqO51ZwokRx0a_qf26KEk` | Curated Known Closure |
| **Standard ToyKraft** | 722 Metropolitan Ave, Brooklyn, NY 11211, USA | `ChIJq5-6J1dZwokR9-o7VaUs5uU` | Curated Known Closure |
| **Mary Boone Gallery** | 745 5th Ave, New York, NY 10151, USA | `ChIJ443ZjbdZwokRS_zYZ4d_WRE` | Curated Known Closure |

*(Showing first 30 of 3 confirmed closed venues)*
