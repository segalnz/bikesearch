"""Cached source-backed research, separate from per-listing evidence."""

SEEDS = {
    "Ninja 650": {
        "generation": "2020+",
        "last_checked": "2026-10-13",
        "memo": "US Ninja 650 OEM parts diagrams are available. Exact NZ/US variant compatibility, private-owner workshop manual edition, aftermarket stock and landed prices need verification; no availability or reliability score inferred.",
        "us_sale": "US owner centre lists the 2026 Ninja 650 and ABS variants",
        "manual": "Owner/service manual portal identified; workshop edition and private-owner purchase not yet verified",
        "diagnostics": "Proprietary diagnostics requirements unverified",
        "routine_parts": "OEM parts diagrams available; aftermarket stock and prices unverified",
        "major_parts": "OEM chassis electrical diagram available; component availability and NZ compatibility unverified",
        "local_support": "Cyclespot Wellington service department; exact Kawasaki model support must be confirmed",
        "landed_cost": "Shipping, exchange rate and GST unknown; compare quoted total landed cost",
        "sources": [
            {
                "url": "https://www.kawasaki.com/en-us/owner-center/parts/2026/EX650PTFAN",
                "claim": "US 2026 Ninja 650 OEM parts portal",
            },
            {
                "url": "https://www.kawasaki.com/en-us/owner-center/parts/363732/2026/EX650PTFAL",
                "claim": "ABS chassis electrical parts diagram",
            },
            {
                "url": "https://www.kawasaki.com/en-us/owner-center/service-manuals/2026/ex650ptfal",
                "claim": "Manual portal; exact workshop manual purchase unverified",
            },
            {
                "url": "https://cyclespotwellington.co.nz/",
                "claim": "Lower Hutt location and service department",
            },
        ],
    },
    "GSX-8R": {
        "generation": "2024+",
        "last_checked": "2026-10-13",
        "memo": "Suzuki USA officially lists the 2024 GSX-8R. A Suzuki service bulletin identifies a workshop manual, but private-owner purchase and NZ compatibility need checking. Aftermarket stock, prices and diagnostics remain unverified.",
        "us_sale": "Official Suzuki USA 2024 model page verified",
        "manual": "Suzuki US bulletin references GSX800FM4 service manual 99500-25L12-03E; private-owner availability and later/NZ edition compatibility unverified",
        "diagnostics": "Proprietary diagnostics requirements unverified",
        "routine_parts": "US aftermarket compatibility, stock and prices unverified",
        "major_parts": "US aftermarket compatibility, stock and prices unverified",
        "local_support": "TSS identifies itself as an official Suzuki stockist with a workshop; confirm diagnostics and manual supply",
        "landed_cost": "Shipping, exchange rate and GST unknown; compare quoted total landed cost",
        "sources": [
            {
                "url": "https://suzukicycles.com/street/2024/gsx-8r",
                "claim": "Official US 2024 model listing",
            },
            {
                "url": "https://static.nhtsa.gov/odi/rcl/2024/RCRIT-24V081-9902.pdf",
                "claim": "Suzuki bulletin reference to model-specific workshop manual",
            },
            {
                "url": "https://tssmotorcycles.co.nz/",
                "claim": "Official Suzuki stockist and workshop in Lower Hutt",
            },
        ],
    },
}
