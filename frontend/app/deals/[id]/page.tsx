import { DealPage } from "@/components/deal-page";

// Despliegue de un solo servicio: el frontend se exporta como sitio estático y una única página sirve a todas las
// operaciones. El backend la entrega para cualquier /deals/<id> y el id se lee de la URL en el navegador.
// En desarrollo (next dev) cualquier id funciona igual que antes.
export function generateStaticParams() {
  return [{ id: "_" }];
}

export default function Page() {
  return <DealPage />;
}
