/** Strict web-only administration contracts. */
import {z} from 'zod';
import {features} from './contracts';
const id=z.string().min(1).max(128),epoch=z.number().finite().nullable();
const member=z.strictObject({id,username:z.string().max(32),role:z.enum(['admin','member']),status:z.enum(['active','suspended'])});
const invite=z.strictObject({id,created_at:z.number().finite(),expires_at:z.number().finite(),consumed:z.boolean(),revoked:z.boolean()});
const audit=z.strictObject({id,actor_id:id.nullable(),target_id:id.nullable(),action:z.string().max(64),occurred_at:z.number().finite(),result:z.enum(['ok','denied'])});
const observation=z.strictObject({status:z.enum(['responsive','stale','unavailable']),observed_at:epoch,progress_at:epoch,state:z.enum(['idle','busy','draining','blocked']).nullable()});
export const adminMembers=z.strictObject({items:z.array(member).max(100),next_cursor:id.nullable()});
export const adminInvites=z.strictObject({items:z.array(invite).max(100),next_cursor:id.nullable()});
export const adminAudit=z.strictObject({items:z.array(audit).max(100),next_cursor:id.nullable()});
export const adminFeature=z.strictObject({name:z.enum(features),enabled:z.boolean(),version:z.number().int().positive()});
export const adminToken=z.strictObject({id,token:z.string().max(128),expires_at:z.number().finite()});
export const adminHealth=z.strictObject({checked_at:z.number().finite(),api:observation,frontend:observation,supervisor:observation,compute:observation,
 queue:z.strictObject({queued:z.number().int().nonnegative(),running:z.number().int().nonnegative(),draining:z.number().int().nonnegative(),oldest_age_seconds:epoch}),
 sources:z.array(z.strictObject({source:z.string().max(64),checked_at:epoch,succeeded_at:epoch,stale:z.boolean()})).max(6),
 failures:z.array(z.strictObject({code:z.string().max(64),count:z.number().int().nonnegative()})).max(4),
 usage:z.strictObject({runs:z.number().int().nonnegative(),input_tokens:z.number().int().nonnegative().nullable(),output_tokens:z.number().int().nonnegative().nullable(),cost:epoch,known_usage_runs:z.number().int().nonnegative()})});
export type AdminMembers=z.infer<typeof adminMembers>;
export type AdminInvites=z.infer<typeof adminInvites>;
export type AdminAudit=z.infer<typeof adminAudit>;
export type AdminHealth=z.infer<typeof adminHealth>;
export type AdminToken=z.infer<typeof adminToken>;
export function adminSchema(path:string){return path.startsWith('/admin/features/')?adminFeature:path.endsWith('/reset-link')||path==='/admin/invites'?adminToken:path.startsWith('/admin/invites?')?adminInvites:path.startsWith('/admin/members')?adminMembers:path.startsWith('/admin/audit')?adminAudit:adminHealth;}
