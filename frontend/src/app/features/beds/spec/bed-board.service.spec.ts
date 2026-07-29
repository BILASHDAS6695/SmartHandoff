import { TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { BedBoardService } from '../services/bed-board.service';
import { BedItem } from '../models/bed.model';
import { environment } from '@environments/environment';

describe('BedBoardService', () => {
  let service: BedBoardService;
  let httpTestingController: HttpTestingController;

  const mockBedItem: BedItem = {
    bedId: '3A-02',
    unit: '3A',
    room: 'Room 200',
    bedNumber: '2',
    bedStatus: 'OCCUPIED',
    encounterId: 'ENC-12345',
    lastUpdated: '2026-07-29T10:00:00Z',
    predictedDischargeTime: '2026-07-30T14:00:00Z',
    dischargePredictionConfidence: 'high',
    dischargePredictionIntervalHours: 2,
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [BedBoardService],
    });
    service = TestBed.inject(BedBoardService);
    httpTestingController = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpTestingController.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should fetch beds with include_predictions parameter', () => {
    service.getBeds(true).subscribe();
    const req = httpTestingController.expectOne(
      `${environment.apiUrl}/api/v1/beds?include_predictions=true`
    );
    expect(req.request.method).toBe('GET');
  });

  it('should fetch beds without predictions parameter when false', () => {
    service.getBeds(false).subscribe();
    const req = httpTestingController.expectOne(
      `${environment.apiUrl}/api/v1/beds?include_predictions=false`
    );
    expect(req.request.method).toBe('GET');
  });

  it('should map BedItem to BedDto with high confidence → LOW risk', (done) => {
    const mockItems: BedItem[] = [mockBedItem];
    service.getBeds().subscribe(result => {
      expect(result.length).toBe(1);
      const mapped = result[0];
      expect(mapped.bedId).toBe('3A-02');
      expect(mapped.unit).toBe('3A');
      expect(mapped.status).toBe('OCCUPIED');
      expect(mapped.riskTier).toBe('LOW'); // high confidence → LOW risk
      expect(mapped.predictedDischargeTime).toBe('2026-07-30T14:00:00Z');
      done();
    });

    const req = httpTestingController.expectOne(
      `${environment.apiUrl}/api/v1/beds?include_predictions=true`
    );
    req.flush(mockItems);
  });

  it('should map medium confidence → MEDIUM risk', (done) => {
    const mediumConfidenceBed: BedItem = {
      ...mockBedItem,
      dischargePredictionConfidence: 'medium',
    };
    service.getBeds().subscribe(result => {
      expect(result[0].riskTier).toBe('MEDIUM');
      done();
    });

    const req = httpTestingController.expectOne(
      `${environment.apiUrl}/api/v1/beds?include_predictions=true`
    );
    req.flush([mediumConfidenceBed]);
  });

  it('should map low confidence → HIGH risk', (done) => {
    const lowConfidenceBed: BedItem = {
      ...mockBedItem,
      dischargePredictionConfidence: 'low',
    };
    service.getBeds().subscribe(result => {
      expect(result[0].riskTier).toBe('HIGH');
      done();
    });

    const req = httpTestingController.expectOne(
      `${environment.apiUrl}/api/v1/beds?include_predictions=true`
    );
    req.flush([lowConfidenceBed]);
  });

  it('should handle null dischargePredictionConfidence', (done) => {
    const noPredictionBed: BedItem = {
      ...mockBedItem,
      dischargePredictionConfidence: null,
    };
    service.getBeds().subscribe(result => {
      expect(result[0].riskTier).toBeNull();
      done();
    });

    const req = httpTestingController.expectOne(
      `${environment.apiUrl}/api/v1/beds?include_predictions=true`
    );
    req.flush([noPredictionBed]);
  });

  it('should map multiple beds with different confidence levels', (done) => {
    const beds: BedItem[] = [
      { ...mockBedItem, bedId: 'BED-1', dischargePredictionConfidence: 'high' },
      { ...mockBedItem, bedId: 'BED-2', dischargePredictionConfidence: 'medium' },
      { ...mockBedItem, bedId: 'BED-3', dischargePredictionConfidence: 'low' },
    ];
    service.getBeds().subscribe(result => {
      expect(result.length).toBe(3);
      expect(result[0].riskTier).toBe('LOW');
      expect(result[1].riskTier).toBe('MEDIUM');
      expect(result[2].riskTier).toBe('HIGH');
      done();
    });

    const req = httpTestingController.expectOne(
      `${environment.apiUrl}/api/v1/beds?include_predictions=true`
    );
    req.flush(beds);
  });
});
