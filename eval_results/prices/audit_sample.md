# Audit humain du matching prix (échantillon stratifié)

Pour chaque ligne : ouvrir l'URL, vérifier que la fiche motoplanete
correspond bien à **notre moto** (bonne variante, bonne année) et que
le prix affiché est celui de la fiche. Remplir `verdict` avec `ok`
ou `ko` (et un mot de raison après `ko:` si utile).

| # | verdict | notre moto | prix retenu | fiche motoplanete | match | url |
|---|---------|-----------|-------------|-------------------|-------|-----|
| 1 | ok | Honda CB1000R 5Four 2021 | 19900 € | honda CB 1000 R 5Four 2021 | forward+0 | https://www.motoplanete.com/honda/8855/CB-1000-R-5Four-2021/contact.html |
| 2 | ok | Kawasaki Ninja ZX -6R 2010 | 10999 € | kawasaki ZX-6R 600 2010 | forward+0 | https://www.motoplanete.com/kawasaki/1547/ZX-6R-600-2010/contact.html |
| 3 | ok | Honda NT 650 V Deauville 2000 | 8450 € | honda NT 650 V DEAUVILLE 2000 | forward+0 | https://www.motoplanete.com/honda/437/NT-650-V-DEAUVILLE-2000/contact.html |
| 4 | ok | Moto Guzzi V100 Mandello 2023 | 15499 € | moto guzzi V 100 Mandello 2023 | forward+0 | https://www.motoplanete.com/moto-guzzi/10585/V-100-Mandello-2023/contact.html |
| 5 | ok | Kawasaki VN 900 Custom 2012 | 8899 € | kawasaki VN 900 Custom 2012 | forward+0 | https://www.motoplanete.com/kawasaki/3644/VN-900-Custom-2012/contact.html |
| 6 | ok | Kawasaki KMX 125 1998 | 3200 € | kawasaki KMX 125 1998 | forward+0 | https://www.motoplanete.com/kawasaki/3261/KMX-125-1998/contact.html |
| 7 | ok | Moto Guzzi California Classic 2010 | 13490 € | moto guzzi 1100 CALIFORNIA Classic 2010 | forward+0 | https://www.motoplanete.com/moto-guzzi/2976/1100-CALIFORNIA-Classic-2010/contact.html |
| 8 | ok | Suzuki GSX-R 1000 2004 | 12999 € | suzuki GSX-R 1000 2004 | forward+0 | https://www.motoplanete.com/suzuki/1920/GSX-R-1000-2004/contact.html |
| 9 | ok | Indian FTR Sport 2024 | 17190 € | indian FTR 1200 Sport 2024 | forward+0 | https://www.motoplanete.com/indian/10492/FTR-1200-Sport-2024/contact.html |
| 10 | ok | Yamaha TDM 900 2004 | 9145 € | yamaha TDM 900 2004 | forward+0 | https://www.motoplanete.com/yamaha/1447/TDM-900-2004/contact.html |
| 11 | ok | Kawasaki KX450 2023 | 9899 € | kawasaki KX 450 2023 | forward+0 | https://www.motoplanete.com/kawasaki/9411/KX-450-2023/contact.html |
| 12 | ok | Moto Guzzi V9 Roamer 2024 | 10499 € | moto guzzi 850 V9 Roamer 2024 | forward+0 | https://www.motoplanete.com/moto-guzzi/10569/850-V9-Roamer-2024/contact.html |
| 13 | ok | MV Agusta Turismo Veloce 800 2019 | 16990 € | mv agusta 800 Turismo Veloce 2019 | forward+0 | https://www.motoplanete.com/mv-agusta/7464/800-Turismo-Veloce-2019/contact.html |
| 14 | ok | MV Agusta Brutale 1078RR 2008 | 18490 € | mv agusta Brutale 1078 RR 2008 | forward+0 | https://www.motoplanete.com/mv-agusta/1240/Brutale-1078-RR-2008/contact.html |
| 15 | ok | Ducati XDiavel 2020 | 21290 € | ducati 1262 XDiavel 2020 | forward+0 | https://www.motoplanete.com/ducati/8137/1262-XDiavel-2020/contact.html |
| 16 | ok | Kawasaki Ninja ZX-10R ABS 2016 | 17599 € | kawasaki ZX-10R 1000 2016 | forward+0 | https://www.motoplanete.com/kawasaki/5620/ZX-10R-1000-2016/contact.html |
| 17 | ok | Aprilia RSV Mille 2002 | 12855 € | aprilia RSV 1000 2002 | forward+0 | https://www.motoplanete.com/aprilia/555/RSV-1000-2002/contact.html |
| 18 | ok | Dodge Tomahawk 2003 | 400000 € | dodge 8300 TOMAHAWK 2003 | forward+0 | https://www.motoplanete.com/dodge/523/8300-TOMAHAWK-2003/contact.html |
| 19 | ok | Harley-Davidson Sportster XL 883N Iron 883 2010 | 8310 € | harley davidson XL 883 SPORTSTER IRON 2010 | forward+0 | https://www.motoplanete.com/harley-davidson/1333/XL-883-SPORTSTER-IRON-2010/contact.html |
| 20 | ok | Kawasaki Eliminator 125 2005 | 3459 € | kawasaki 125 ELIMINATOR 2005 | forward+0 | https://www.motoplanete.com/kawasaki/2925/125-ELIMINATOR-2005/contact.html |
| 21 | ok | Harley-Davidson FXSTD Softail Deuce 2000 | 21270 € | harley davidson 1450 SOFTAIL DEUCE FXSTD 2001 | année-1 | https://www.motoplanete.com/harley-davidson/3139/1450-SOFTAIL-DEUCE-FXSTD-2001/contact.html |
| 22 | ok | Zero DSR 2019 | 17840 € | zero motorcycles DSR 2020 | année-1 | https://www.motoplanete.com/zero-motorcycles/8096/DSR-2020/contact.html |
| 23 | ok | Ducati Scrambler 1100 Tribute Pro 2022 | 15490 € | ducati Scrambler 1100 Tribute Pro 2023 | année-1 | https://www.motoplanete.com/ducati/10051/Scrambler-1100-Tribute-Pro-2023/contact.html |
| 24 | ok | Honda VTR 1000 F FireStorm - Super Hawk 2003 | 9900 € | honda VTR 1000 F FIRESTORM 2004 | année-1 | https://www.motoplanete.com/honda/469/VTR-1000-F-FIRESTORM--2004/contact.html |
| 25 | ok | Ducati XDiavel S 2021 | 25390 € | ducati 1262 XDiavel S 2022 | année-1 | https://www.motoplanete.com/ducati/9100/1262-XDiavel-S-2022/contact.html |
| 26 | ok | Suzuki VZ 800 Marauder 2003 | 12999 € | suzuki VZ 1600 MARAUDER 2004 | année-1 | https://www.motoplanete.com/suzuki/2682/VZ-1600-MARAUDER-2004/contact.html |
| 27 | ok | Honda CBR600RR 2024 | 11699 € | honda CBR 600 RR 2025 | année-1 | https://www.motoplanete.com/honda/11046/CBR-600-RR-2025/contact.html |
| 28 | ok | CF Moto 650MT 2022 | 6990 € | cfmoto 700 MT 2023 | année-1 | https://www.motoplanete.com/cfmoto/10716/700-MT-2023/contact.html |
| 29 | ok | Moto Guzzi V85 TT 2024 | 13499 € | moto guzzi V 85 TT 2025 | année-1 | https://www.motoplanete.com/moto-guzzi/10924/V-85-TT-2025/contact.html |
| 30 | ok | Moto Morini X-Cape 2020 | 7599 € | morini 650 X-Cape 2021 | année-1 | https://www.motoplanete.com/morini/8867/650-X-Cape-2021/contact.html |
| 31 | ok | Honda CX 650 Turbo 1985 | 6662 € | honda CX 650 Turbo 1986 | année-1 | https://www.motoplanete.com/honda/6298/CX-650-Turbo-1986/contact.html |
| 32 | ok | Moto Guzzi California EV 2006 | 13490 € | moto guzzi 1100 CALIFORNIA EV 2007 | année-1 | https://www.motoplanete.com/moto-guzzi/2991/1100-CALIFORNIA-EV-2007/contact.html |
| 33 | ok | Tacita T-Cruise Turismo 2019 | 9300 € | tacita T-CRUISE 2018 | année+1 | https://www.motoplanete.com/tacita/6845/T-CRUISE-2018/contact.html |
| 34 | ok | MV Agusta Brutale 800 R 2024 | 15600 € | mv agusta 800 Brutale R 2023 | année+1 | https://www.motoplanete.com/mv-agusta/9699/800-Brutale-R-2023/contact.html |
| 35 | ok | Harley-Davidson FLHR Road King 2003 | 20250 € | harley davidson 1450 ROAD KING FLHR 2004 | année-1 | https://www.motoplanete.com/harley-davidson/3674/1450-ROAD-KING-FLHR-2004/contact.html |
| 36 | ok | Suzuki GSX-S950 2022 | 11549 € | suzuki GSX-S 950 R'' Design 2022 | reverse | https://www.motoplanete.com/suzuki/9417/GSX-S-950-R-Design-2022/contact.html |
| 37 | ok | Ducati Multistrada V4 2024 | 27590 € | ducati Multistrada V4 Rally 1160 2024 | reverse | https://www.motoplanete.com/ducati/10205/Multistrada-V4-Rally-1160-2024/contact.html |
| 38 | ok | Moto Guzzi Stelvio 2008 | 13590 € | moto guzzi STELVIO 1200 4V 2008 | reverse | https://www.motoplanete.com/moto-guzzi/95/STELVIO-1200-4V-2008/contact.html |
| 39 | ok | Harley-Davidson Tri Glide Ultra 2021 | 40190 € | harley davidson 1870 Tri Glide Ultra FLHTCUTG 2021 | reverse | https://www.motoplanete.com/harley-davidson/8685/1870-Tri-Glide-Ultra-FLHTCUTG-2021/contact.html |
| 40 | ok | Mash British Seven 125 2023 | 3799 € | mash 125 Black / British Seven 2022 | reverse | https://www.motoplanete.com/mash/9326/125-Black--British-Seven-2022/contact.html |
| 41 | ok | Yamaha FZ6 2005 | 7390 € | yamaha FZ6 600 FAZER 2005 | reverse | https://www.motoplanete.com/yamaha/2003/FZ6-600-FAZER-2005/contact.html |
| 42 | ok | Harley-Davidson Roadster 2020 | 13120 € | harley davidson XL 1200 CX Sportster Roadster 2020 | reverse | https://www.motoplanete.com/harley-davidson/8046/XL-1200-CX-Sportster-Roadster-2020/contact.html |
| 43 | ok | Yamaha XVS1300A Midnight Star 2015 | 12999 € | yamaha XVS 1300 A Midnight Star CFD 2015 | reverse | https://www.motoplanete.com/yamaha/5306/XVS-1300-A-Midnight-Star-CFD-2015/contact.html |
| 44 | ok | Yamaha YBR125 2013 | 2599 € | yamaha YBR 125 Cruiser 2013 | reverse | https://www.motoplanete.com/yamaha/4580/YBR-125-Cruiser-2013/contact.html |
| 45 | ok | Aprilia Dorsoduro 750 2012 | 7999 € | aprilia SMV 750 DORSODURO 2012 | reverse | https://www.motoplanete.com/aprilia/3869/SMV-750-DORSODURO-2012/contact.html |
| 46 | ok | BMW R 1150 R 2003 | 12100 € | bmw R 1150 R  Rockster 2003 | reverse | https://www.motoplanete.com/bmw/1976/R-1150-R--Rockster-2003/contact.html |
| 47 | ok | Honda Varadero 125 2011 | 4990 € | honda 125 VARADERO XLV 2011 | reverse | https://www.motoplanete.com/honda/2804/125-VARADERO-XLV-2011/contact.html |
| 48 | ok | Brough Superior SS100 2020 | 65000 € | brough superior SS 100 MK2 2021 | reverse | https://www.motoplanete.com/brough-superior/8741/SS-100-MK2-2021/contact.html |
| 49 | ok | Suzuki GW250 2013 | 3999 € | suzuki GW 250 INAZUMA 2013 | reverse | https://www.motoplanete.com/suzuki/4544/GW-250-INAZUMA-2013/contact.html |
| 50 | ok | Harley-Davidson XR1200X 2010 | 11995 € | harley davidson XR 1200 X Sportster 2010 | reverse | https://www.motoplanete.com/harley-davidson/1308/XR-1200-X-Sportster-2010/contact.html |
