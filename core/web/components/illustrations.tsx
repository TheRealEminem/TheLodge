// The app's artwork comes from its identity (identity/art.tsx), so core/ is the same in every family app. Each
// identity exports Logo, Scene, Ambient and Badge; modules import them from here, never from @identity.
export { Ambient, Badge, Badge as ContourBadge, Logo, Scene } from "@identity/art";
