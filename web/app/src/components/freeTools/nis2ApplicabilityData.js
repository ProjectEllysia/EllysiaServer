/**
 * Actividades de los anexos I y II de la Directiva (UE) 2022/2555 (NIS2), en el orden de la directiva.
 *
 * Cada actividad lleva su anexo, su sector y su nombre en castellano (literal del texto oficial) y en
 * inglés, y una `rule` si el tipo de servicio tiene una regla propia en los artículos 2 y 3 (DNS y
 * registros de primer nivel, servicios de confianza, comunicaciones electrónicas públicas,
 * Administración central o regional). Es un módulo JavaScript y no un JSON para que lo lean
 * igual el navegador y `node`.
 */
export default {
 "version": "1",
 "annexes": {
  "I": [
   {
    "id": "I.1.a",
    "annex": "I",
    "sector": {
     "id": "I.1",
     "es": "Energía",
     "en": "Energy"
    },
    "es": "Electricidad",
    "en": "Electricity",
    "rule": null
   },
   {
    "id": "I.1.b",
    "annex": "I",
    "sector": {
     "id": "I.1",
     "es": "Energía",
     "en": "Energy"
    },
    "es": "Sistemas urbanos de calefacción y de refrigeración",
    "en": "District heating and cooling",
    "rule": null
   },
   {
    "id": "I.1.c",
    "annex": "I",
    "sector": {
     "id": "I.1",
     "es": "Energía",
     "en": "Energy"
    },
    "es": "Crudo",
    "en": "Oil",
    "rule": null
   },
   {
    "id": "I.1.d",
    "annex": "I",
    "sector": {
     "id": "I.1",
     "es": "Energía",
     "en": "Energy"
    },
    "es": "Gas",
    "en": "Gas",
    "rule": null
   },
   {
    "id": "I.1.e",
    "annex": "I",
    "sector": {
     "id": "I.1",
     "es": "Energía",
     "en": "Energy"
    },
    "es": "Hidrógeno",
    "en": "Hydrogen",
    "rule": null
   },
   {
    "id": "I.2.a",
    "annex": "I",
    "sector": {
     "id": "I.2",
     "es": "Transporte",
     "en": "Transport"
    },
    "es": "Transporte aéreo",
    "en": "Air transport",
    "rule": null
   },
   {
    "id": "I.2.b",
    "annex": "I",
    "sector": {
     "id": "I.2",
     "es": "Transporte",
     "en": "Transport"
    },
    "es": "Transporte por ferrocarril",
    "en": "Rail transport",
    "rule": null
   },
   {
    "id": "I.2.c",
    "annex": "I",
    "sector": {
     "id": "I.2",
     "es": "Transporte",
     "en": "Transport"
    },
    "es": "Transporte marítimo y fluvial",
    "en": "Water transport",
    "rule": null
   },
   {
    "id": "I.2.d",
    "annex": "I",
    "sector": {
     "id": "I.2",
     "es": "Transporte",
     "en": "Transport"
    },
    "es": "Transporte por carretera",
    "en": "Road transport",
    "rule": null
   },
   {
    "id": "I.3",
    "annex": "I",
    "sector": {
     "id": "I.3",
     "es": "Banca",
     "en": "Banking"
    },
    "es": "Banca",
    "en": "Banking",
    "rule": null
   },
   {
    "id": "I.4",
    "annex": "I",
    "sector": {
     "id": "I.4",
     "es": "Infraestructuras de los mercados financieros",
     "en": "Financial market infrastructures"
    },
    "es": "Infraestructuras de los mercados financieros",
    "en": "Financial market infrastructures",
    "rule": null
   },
   {
    "id": "I.5",
    "annex": "I",
    "sector": {
     "id": "I.5",
     "es": "Sector sanitario",
     "en": "Health"
    },
    "es": "Sector sanitario",
    "en": "Health",
    "rule": null
   },
   {
    "id": "I.6",
    "annex": "I",
    "sector": {
     "id": "I.6",
     "es": "Agua potable",
     "en": "Drinking water"
    },
    "es": "Agua potable",
    "en": "Drinking water",
    "rule": null
   },
   {
    "id": "I.7",
    "annex": "I",
    "sector": {
     "id": "I.7",
     "es": "Aguas residuales",
     "en": "Waste water"
    },
    "es": "Aguas residuales",
    "en": "Waste water",
    "rule": null
   },
   {
    "id": "I.8.ixp",
    "annex": "I",
    "sector": {
     "id": "I.8",
     "es": "Infraestructura digital",
     "en": "Digital infrastructure"
    },
    "es": "Proveedores de puntos de intercambio de internet",
    "en": "Internet exchange point providers",
    "rule": null
   },
   {
    "id": "I.8.dns",
    "annex": "I",
    "sector": {
     "id": "I.8",
     "es": "Infraestructura digital",
     "en": "Digital infrastructure"
    },
    "es": "Proveedores de servicios de DNS, excluidos los operadores de servidores raíz",
    "en": "DNS service providers, excluding root name server operators",
    "rule": "dns_or_tld"
   },
   {
    "id": "I.8.tld",
    "annex": "I",
    "sector": {
     "id": "I.8",
     "es": "Infraestructura digital",
     "en": "Digital infrastructure"
    },
    "es": "Registros de nombres de dominio de primer nivel",
    "en": "Top-level domain name registries",
    "rule": "dns_or_tld"
   },
   {
    "id": "I.8.cloud",
    "annex": "I",
    "sector": {
     "id": "I.8",
     "es": "Infraestructura digital",
     "en": "Digital infrastructure"
    },
    "es": "Proveedores de servicios de computación en nube",
    "en": "Cloud computing service providers",
    "rule": null
   },
   {
    "id": "I.8.datacenter",
    "annex": "I",
    "sector": {
     "id": "I.8",
     "es": "Infraestructura digital",
     "en": "Digital infrastructure"
    },
    "es": "Proveedores de servicios de centro de datos",
    "en": "Data centre service providers",
    "rule": null
   },
   {
    "id": "I.8.cdn",
    "annex": "I",
    "sector": {
     "id": "I.8",
     "es": "Infraestructura digital",
     "en": "Digital infrastructure"
    },
    "es": "Proveedores de redes de distribución de contenidos",
    "en": "Content delivery network providers",
    "rule": null
   },
   {
    "id": "I.8.trust",
    "annex": "I",
    "sector": {
     "id": "I.8",
     "es": "Infraestructura digital",
     "en": "Digital infrastructure"
    },
    "es": "Prestadores de servicios de confianza",
    "en": "Trust service providers",
    "rule": "trust"
   },
   {
    "id": "I.8.publicNetwork",
    "annex": "I",
    "sector": {
     "id": "I.8",
     "es": "Infraestructura digital",
     "en": "Digital infrastructure"
    },
    "es": "Proveedores de redes públicas de comunicaciones electrónicas",
    "en": "Providers of public electronic communications networks",
    "rule": "public_comms"
   },
   {
    "id": "I.8.publicService",
    "annex": "I",
    "sector": {
     "id": "I.8",
     "es": "Infraestructura digital",
     "en": "Digital infrastructure"
    },
    "es": "Proveedores de servicios de comunicaciones electrónicas disponibles para el público",
    "en": "Providers of publicly available electronic communications services",
    "rule": "public_comms"
   },
   {
    "id": "I.9",
    "annex": "I",
    "sector": {
     "id": "I.9",
     "es": "Gestión de servicios de TIC (de empresa a empresa)",
     "en": "ICT service management (business-to-business)"
    },
    "es": "Gestión de servicios de TIC (de empresa a empresa)",
    "en": "ICT service management (business-to-business)",
    "rule": null
   },
   {
    "id": "I.10.central",
    "annex": "I",
    "sector": {
     "id": "I.10",
     "es": "Entidades de la Administración pública, con exclusión del poder judicial, los parlamentos y los bancos centrales",
     "en": "Public administration"
    },
    "es": "Entidades de la Administración pública central",
    "en": "Central government entities",
    "rule": "central_admin"
   },
   {
    "id": "I.10.regional",
    "annex": "I",
    "sector": {
     "id": "I.10",
     "es": "Entidades de la Administración pública, con exclusión del poder judicial, los parlamentos y los bancos centrales",
     "en": "Public administration"
    },
    "es": "Entidades de la Administración pública a escala regional",
    "en": "Regional government entities",
    "rule": "regional_admin"
   },
   {
    "id": "I.11",
    "annex": "I",
    "sector": {
     "id": "I.11",
     "es": "Espacio",
     "en": "Space"
    },
    "es": "Espacio",
    "en": "Space",
    "rule": null
   }
  ],
  "II": [
   {
    "id": "II.1",
    "annex": "II",
    "sector": {
     "id": "II.1",
     "es": "Servicios postales y de mensajería",
     "en": "Postal and courier services"
    },
    "es": "Servicios postales y de mensajería",
    "en": "Postal and courier services",
    "rule": null
   },
   {
    "id": "II.2",
    "annex": "II",
    "sector": {
     "id": "II.2",
     "es": "Gestión de residuos",
     "en": "Waste management"
    },
    "es": "Gestión de residuos",
    "en": "Waste management",
    "rule": null
   },
   {
    "id": "II.3",
    "annex": "II",
    "sector": {
     "id": "II.3",
     "es": "Fabricación, producción y distribución de sustancias y mezclas químicas",
     "en": "Manufacture, production and distribution of chemicals"
    },
    "es": "Fabricación, producción y distribución de sustancias y mezclas químicas",
    "en": "Manufacture, production and distribution of chemicals",
    "rule": null
   },
   {
    "id": "II.4",
    "annex": "II",
    "sector": {
     "id": "II.4",
     "es": "Producción, transformación y distribución de alimentos",
     "en": "Production, processing and distribution of food"
    },
    "es": "Producción, transformación y distribución de alimentos",
    "en": "Production, processing and distribution of food",
    "rule": null
   },
   {
    "id": "II.5.a",
    "annex": "II",
    "sector": {
     "id": "II.5",
     "es": "Fabricación",
     "en": "Manufacturing"
    },
    "es": "Fabricación de productos sanitarios y productos sanitarios para diagnóstico in vitro",
    "en": "Manufacture of medical devices and in vitro diagnostic medical devices",
    "rule": null
   },
   {
    "id": "II.5.b",
    "annex": "II",
    "sector": {
     "id": "II.5",
     "es": "Fabricación",
     "en": "Manufacturing"
    },
    "es": "Fabricación de productos informáticos, electrónicos y ópticos",
    "en": "Manufacture of computer, electronic and optical products",
    "rule": null
   },
   {
    "id": "II.5.c",
    "annex": "II",
    "sector": {
     "id": "II.5",
     "es": "Fabricación",
     "en": "Manufacturing"
    },
    "es": "Fabricación de material eléctrico",
    "en": "Manufacture of electrical equipment",
    "rule": null
   },
   {
    "id": "II.5.d",
    "annex": "II",
    "sector": {
     "id": "II.5",
     "es": "Fabricación",
     "en": "Manufacturing"
    },
    "es": "Fabricación de maquinaria y equipo n.c.o.p.",
    "en": "Manufacture of machinery and equipment n.e.c.",
    "rule": null
   },
   {
    "id": "II.5.e",
    "annex": "II",
    "sector": {
     "id": "II.5",
     "es": "Fabricación",
     "en": "Manufacturing"
    },
    "es": "Fabricación de vehículos de motor, remolques y semirremolques",
    "en": "Manufacture of motor vehicles, trailers and semi-trailers",
    "rule": null
   },
   {
    "id": "II.5.f",
    "annex": "II",
    "sector": {
     "id": "II.5",
     "es": "Fabricación",
     "en": "Manufacturing"
    },
    "es": "Fabricación de otro material de transporte",
    "en": "Manufacture of other transport equipment",
    "rule": null
   },
   {
    "id": "II.6",
    "annex": "II",
    "sector": {
     "id": "II.6",
     "es": "Proveedores de servicios digitales",
     "en": "Digital providers"
    },
    "es": "Proveedores de servicios digitales",
    "en": "Digital providers",
    "rule": null
   },
   {
    "id": "II.7",
    "annex": "II",
    "sector": {
     "id": "II.7",
     "es": "Investigación",
     "en": "Research"
    },
    "es": "Investigación",
    "en": "Research",
    "rule": null
   }
  ]
 }
}
