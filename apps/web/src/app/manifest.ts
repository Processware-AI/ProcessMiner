import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "ProcessMiner",
    short_name: "ProcessMiner",
    description: "프로세스 자산과 결과물을 일관되게 유지관리하는 플랫폼",
    lang: "ko",
    start_url: "/",
    display: "standalone",
    background_color: "#fcfcfd",
    theme_color: "#3b4cb8",
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/icon-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
    ],
  };
}
