// Minimal shim for Next.js imports when node_modules aren't installed locally.
// Keep this file with NO imports/exports so the module declarations are global.

declare module "next/link" {
    const Link: any;
    export default Link;
}

declare module "next/navigation" {
    export const redirect: any;
    export const useRouter: any;
}


