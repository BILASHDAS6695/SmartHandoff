/**
 * OfflineCacheService unit tests (US-054 TASK-002).
 *
 * Tests the discharge-date-based cache eviction logic that supplements
 * the Angular Service Worker's maxAge TTL configuration.
 */
import { TestBed } from '@angular/core/testing';
import { OfflineCacheService } from './offline-cache.service';

describe('OfflineCacheService', () => {
  let service: OfflineCacheService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [OfflineCacheService],
    });
    service = TestBed.inject(OfflineCacheService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  describe('evictExpiredDischargeCache', () => {
    it('should return gracefully when caches API is unavailable', async () => {
      const cachesSpy = jasmine.getEnv().spyOnGlobalScope('caches');
      if (cachesSpy) {
        (window as unknown as Record<string, unknown>).caches = undefined;
      }

      await expectAsync(service.evictExpiredDischargeCache()).toBeResolved();
    });

    it('should return gracefully when cache does not exist', async () => {
      spyOn(caches, 'open').and.returnValue(Promise.reject(new Error('Cache not found')));

      await expectAsync(service.evictExpiredDischargeCache()).toBeResolved();
    });

    it('should evict entries whose discharge_date + 30 days has elapsed', async () => {
      const mockCache = jasmine.createSpyObj<Cache>('Cache', ['keys', 'match', 'delete']);

      const oldDischargeDate = new Date();
      oldDischargeDate.setDate(oldDischargeDate.getDate() - 31); // 31 days ago

      const oldResponse = new Response(
        JSON.stringify({ discharge_date: oldDischargeDate.toISOString().split('T')[0] })
      );
      const request = new Request('http://example.com/api/discharge');

      mockCache.keys.and.returnValue(Promise.resolve([request]));
      mockCache.match.and.returnValue(Promise.resolve(oldResponse));
      mockCache.delete.and.returnValue(Promise.resolve(true));

      spyOn(caches, 'open').and.returnValue(Promise.resolve(mockCache));

      await service.evictExpiredDischargeCache();

      expect(mockCache.delete).toHaveBeenCalledWith(request);
    });

    it('should not evict entries within the 30-day TTL', async () => {
      const mockCache = jasmine.createSpyObj<Cache>('Cache', ['keys', 'match', 'delete']);

      const recentDischargeDate = new Date();
      recentDischargeDate.setDate(recentDischargeDate.getDate() - 7); // 7 days ago

      const recentResponse = new Response(
        JSON.stringify({ discharge_date: recentDischargeDate.toISOString().split('T')[0] })
      );
      const request = new Request('http://example.com/api/discharge');

      mockCache.keys.and.returnValue(Promise.resolve([request]));
      mockCache.match.and.returnValue(Promise.resolve(recentResponse));

      spyOn(caches, 'open').and.returnValue(Promise.resolve(mockCache));

      await service.evictExpiredDischargeCache();

      expect(mockCache.delete).not.toHaveBeenCalled();
    });

    it('should gracefully skip entries without discharge_date field', async () => {
      const mockCache = jasmine.createSpyObj<Cache>('Cache', ['keys', 'match', 'delete']);

      const malformedResponse = new Response(JSON.stringify({ some_field: 'value' }));
      const request = new Request('http://example.com/api/discharge');

      mockCache.keys.and.returnValue(Promise.resolve([request]));
      mockCache.match.and.returnValue(Promise.resolve(malformedResponse));

      spyOn(caches, 'open').and.returnValue(Promise.resolve(mockCache));

      await service.evictExpiredDischargeCache();

      expect(mockCache.delete).not.toHaveBeenCalled();
    });

    it('should gracefully skip malformed JSON entries', async () => {
      const mockCache = jasmine.createSpyObj<Cache>('Cache', ['keys', 'match', 'delete']);

      const malformedResponse = new Response('invalid json {]');
      const request = new Request('http://example.com/api/discharge');

      mockCache.keys.and.returnValue(Promise.resolve([request]));
      mockCache.match.and.returnValue(Promise.resolve(malformedResponse));

      spyOn(caches, 'open').and.returnValue(Promise.resolve(mockCache));

      await service.evictExpiredDischargeCache();

      expect(mockCache.delete).not.toHaveBeenCalled();
    });
  });
});
